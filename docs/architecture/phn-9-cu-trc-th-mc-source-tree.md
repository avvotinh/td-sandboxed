# **Phần 9: Cấu trúc thư mục (Source Tree)**

```plaintext
hft-lakehouse/
├── apps/
│   ├── ingestion-client/      # Ứng dụng Go
│   └── processing-job/        # Script Python
├── dags/                      # DAGs của Airflow
├── data/
│   └── cold_storage/          # Chứa file Parquet
├── scripts/                   # Script hỗ trợ, benchmark
├── docs/
│   ├── prd.md
│   └── architecture.md
├── docker-compose.yml
├── .env.example
└── README.md
```
