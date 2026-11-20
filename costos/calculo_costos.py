"""
Estimación de costos mensuales — MediConnect en AWS (región us-east-1)

Precios de lista On-Demand en USD tomados de las páginas oficiales de precios
de AWS / AWS Pricing Calculator. Deben revalidarse en el Pricing Calculator
antes de presentar un presupuesto definitivo, porque AWS puede cambiarlos.

Uso:  python calculo_costos.py   -> genera estimacion_costos.csv y .json
"""
import csv
import json
from pathlib import Path

H = 730            # horas promedio por mes
MONDAYS = 4.33     # lunes promedio por mes
WORKDAYS = 22      # días hábiles por mes

# ---------------------------------------------------------------------------
# Precios unitarios (us-east-1)
# ---------------------------------------------------------------------------
P = {
    "fargate_vcpu_h_arm": 0.03238,   # Fargate Linux/ARM (Graviton) por vCPU-hora
    "fargate_gb_h_arm": 0.00356,     # Fargate Linux/ARM por GB-hora
    "alb_h": 0.0225, "alb_lcu_h": 0.008,
    "nat_h": 0.045, "nat_gb": 0.045,
    "rds_m6g_large_maz_h": 0.304,    # MySQL db.m6g.large Multi-AZ (2 x 0.152)
    "rds_t4g_medium_h": 0.065,       # MySQL db.t4g.medium Single-AZ (réplica)
    "rds_gp3_gb_maz": 0.230, "rds_gp3_gb": 0.115, "rds_backup_gb": 0.095,
    "valkey_t4g_small_h": 0.0256,    # ElastiCache for Valkey cache.t4g.small
    "s3_std_gb": 0.023, "s3_ia_gb": 0.0125,
    "s3_put_1k": 0.005, "s3_get_1k": 0.0004, "xregion_gb": 0.02,
    "cf_gb": 0.085, "cf_10k_https": 0.0100,
    "waf_acl": 5.0, "waf_rule": 1.0, "waf_m_req": 0.60,
    "r53_zone": 0.50, "r53_m_q": 0.40, "r53_hc": 0.50,
    "chime_attendee_min": 0.0017,
    "ses_1k": 0.10,
    "sms_sv": 0.10,                  # SMS a El Salvador (tarifa variable por operador; supuesto)
    "sqs_m": 0.40, "secret": 0.40, "secret_10k": 0.05,
    "kms_key": 1.0, "kms_10k": 0.03,
    "cw_logs_gb": 0.50, "cw_store_gb": 0.03, "cw_alarm": 0.10, "cw_dash": 3.0,
    "ecr_gb": 0.10, "interaz_gb": 0.02,  # 0.01 en cada dirección
}


def fargate(vcpu, gb, task_hours):
    per_task_h = vcpu * P["fargate_vcpu_h_arm"] + gb * P["fargate_gb_h_arm"]
    return per_task_h * task_hours


def task_hours(base, monday_peak=0, weekday_extra=0, peak_hours=10):
    """Horas-tarea al mes: mínimo 24/7 + picos de lunes + refuerzo en horario hábil."""
    return (base * H
            + max(monday_peak - base, 0) * peak_hours * MONDAYS
            + weekday_extra * peak_hours * WORKDAYS)


rows = []


def add(categoria, servicio, configuracion, costo):
    rows.append({"categoria": categoria, "servicio": servicio,
                 "configuracion": configuracion, "costo_mensual_usd": round(costo, 2)})


# --- Cómputo: Amazon ECS sobre AWS Fargate (ARM64 / Graviton) ---------------
add("Cómputo", "Amazon ECS + Fargate — API Laravel",
    "1 vCPU / 2 GB por tarea; mín. 3 tareas 24/7, hasta 30 los lunes (10x)",
    fargate(1, 2, task_hours(3, monday_peak=30, weekday_extra=3)))
add("Cómputo", "Amazon ECS + Fargate — Portal del paciente (Next.js)",
    "0.5 vCPU / 1 GB; mín. 2 tareas, hasta 20 los lunes",
    fargate(0.5, 1, task_hours(2, monday_peak=20, weekday_extra=2)))
add("Cómputo", "Amazon ECS + Fargate — Dashboard del médico (Next.js)",
    "0.5 vCPU / 1 GB; mín. 2 tareas, hasta 6 los lunes",
    fargate(0.5, 1, task_hours(2, monday_peak=6)))
add("Cómputo", "Amazon ECS + Fargate — Worker de notificaciones",
    "0.5 vCPU / 1 GB; 2 tareas 24/7 consumiendo SQS",
    fargate(0.5, 1, 2 * H))
add("Cómputo", "Amazon ECS + Fargate — Tarea de reportes",
    "2 vCPU / 4 GB; ~20 min por semana (EventBridge Scheduler)",
    fargate(2, 4, MONDAYS * (20 / 60)))
add("Cómputo", "Amazon ECR", "10 GB de imágenes Docker", 10 * P["ecr_gb"])

# --- Red y entrega de contenido ----------------------------------------------
add("Red", "Elastic Load Balancing (ALB)", "1 ALB en 2 AZ, ~3 LCU promedio",
    P["alb_h"] * H + 3 * P["alb_lcu_h"] * H)
add("Red", "NAT Gateway", "2 NAT (uno por AZ), 100 GB procesados",
    2 * P["nat_h"] * H + 100 * P["nat_gb"])
add("Red", "Amazon CloudFront", "1.5 TB salida (1 TB capa gratuita) y 20 M solicitudes HTTPS (10 M gratis)",
    512 * P["cf_gb"] + (10_000_000 / 10_000) * P["cf_10k_https"])
add("Red", "AWS WAF", "1 Web ACL, 6 reglas/grupos administrados, 20 M solicitudes",
    P["waf_acl"] + 6 * P["waf_rule"] + 20 * P["waf_m_req"])
add("Red", "Amazon Route 53", "1 zona hospedada, 10 M consultas, 2 health checks",
    P["r53_zone"] + 10 * P["r53_m_q"] + 2 * P["r53_hc"])
add("Red", "Transferencia entre AZ", "~200 GB/mes entre zonas de disponibilidad",
    200 * P["interaz_gb"])

# --- Datos -------------------------------------------------------------------
add("Datos", "Amazon RDS for MySQL — principal Multi-AZ",
    "db.m6g.large Multi-AZ, 200 GB gp3, backups 30 días",
    P["rds_m6g_large_maz_h"] * H + 200 * P["rds_gp3_gb_maz"] + 200 * P["rds_backup_gb"])
add("Datos", "Amazon RDS for MySQL — réplica de lectura",
    "db.t4g.medium Single-AZ, 200 GB gp3 (consultas de reportes)",
    P["rds_t4g_medium_h"] * H + 200 * P["rds_gp3_gb"])
add("Datos", "Amazon ElastiCache (Valkey)", "2 nodos cache.t4g.small (primario + réplica)",
    2 * P["valkey_t4g_small_h"] * H)
add("Datos", "Amazon S3 — archivos médicos",
    "2 TB Standard, versionado + Object Lock, 2 M PUT / 10 M GET",
    2048 * P["s3_std_gb"] + 2000 * P["s3_put_1k"] + 10000 * P["s3_get_1k"])
add("Datos", "Amazon S3 — réplica entre regiones (us-west-2)",
    "2 TB en Standard-IA + 150 GB/mes replicados",
    2048 * P["s3_ia_gb"] + 150 * P["xregion_gb"])
add("Datos", "Amazon S3 — estáticos y reportes", "50 GB Standard", 50 * P["s3_std_gb"])
add("Datos", "AWS Backup", "Copia cross-region de snapshots RDS (200 GB)",
    200 * P["rds_backup_gb"] + 200 * P["xregion_gb"])

# --- Aplicación ----------------------------------------------------------------
add("Aplicación", "Amazon Chime SDK (videoconsultas)",
    "15,000 consultas x 20 min x 2 participantes = 600,000 asistente-min",
    600_000 * P["chime_attendee_min"])
add("Aplicación", "Amazon SES (correo)", "200,000 correos/mes", 200 * P["ses_1k"])
add("Aplicación", "AWS End User Messaging (SMS)",
    "6,000 SMS/mes a El Salvador (~US$0.10 c/u, tarifa variable)", 6000 * P["sms_sv"])
add("Aplicación", "Amazon SQS", "3 M solicitudes (1 M gratis)", 2 * P["sqs_m"])
add("Aplicación", "Amazon EventBridge Scheduler", "Programación semanal de reportes", 0.0)

# --- Seguridad y operación -----------------------------------------------------
add("Seguridad", "AWS Secrets Manager", "6 secretos con rotación, 100k llamadas",
    6 * P["secret"] + 10 * P["secret_10k"])
add("Seguridad", "AWS KMS", "3 claves administradas por el cliente, 2 M solicitudes",
    3 * P["kms_key"] + 200 * P["kms_10k"])
add("Seguridad", "Amazon GuardDuty", "Detección de amenazas (estimado por volumen de eventos)", 30.0)
add("Seguridad", "AWS CloudTrail", "1 trail de eventos de administración", 0.0)
add("Operación", "Amazon CloudWatch", "50 GB logs, 100 GB retenidos, 20 alarmas, 3 dashboards",
    50 * P["cw_logs_gb"] + 100 * P["cw_store_gb"] + 20 * P["cw_alarm"] + 3 * P["cw_dash"])
add("Operación", "AWS Budgets + Cost Anomaly Detection", "Alertas de presupuesto", 0.0)

total = round(sum(r["costo_mensual_usd"] for r in rows), 2)

# Ahorro con compromisos (aplican a cómputo y base de datos)
fargate_total = sum(r["costo_mensual_usd"] for r in rows if "Fargate" in r["servicio"])
rds_total = sum(r["costo_mensual_usd"] for r in rows if r["servicio"].startswith("Amazon RDS"))
savings = {
    "compute_savings_plan_1y_20pct": round(fargate_total * 0.20, 2),
    "rds_reserved_1y_35pct_instancias": round((P["rds_m6g_large_maz_h"] + P["rds_t4g_medium_h"]) * H * 0.35, 2),
}
total_optimizado = round(total - sum(savings.values()), 2)

out = Path(__file__).parent
with open(out / "estimacion_costos.csv", "w", newline="", encoding="utf-8") as f:
    w = csv.DictWriter(f, fieldnames=rows[0].keys())
    w.writeheader()
    w.writerows(rows)
    w.writerow({"categoria": "TOTAL", "servicio": "Total mensual On-Demand", "configuracion": "", "costo_mensual_usd": total})
    w.writerow({"categoria": "TOTAL", "servicio": "Total con Savings Plan + RDS Reserved (1 año)", "configuracion": "", "costo_mensual_usd": total_optimizado})

summary = {"region": "us-east-1", "rows": rows, "total": total,
           "savings": savings, "total_optimizado": total_optimizado,
           "anual": round(total * 12, 2), "anual_optimizado": round(total_optimizado * 12, 2),
           "fargate_total": round(fargate_total, 2), "rds_total": round(rds_total, 2)}
(out / "estimacion_costos.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

for r in rows:
    print(f'{r["categoria"]:<11} {r["servicio"]:<58} {r["costo_mensual_usd"]:>9.2f}')
print(f'{"TOTAL On-Demand":<70} {total:>9.2f}')
print(f'{"Ahorros":<70} {savings}')
print(f'{"TOTAL optimizado":<70} {total_optimizado:>9.2f}')
