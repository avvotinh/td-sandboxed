# HFT Lakehouse

A high-frequency trading data lakehouse system for ingesting, processing, and storing market data.

## Project Overview

This project implements a lakehouse architecture for handling high-frequency trading (HFT) data with the following components:
- **Ingestion Client** (Go): Real-time market data ingestion
- **Processing Job** (Python): Data transformation and aggregation
- **Redis**: Hot storage for latest tick data and caching
- **TimescaleDB**: Time-series database for hot storage
- **Cold Storage**: Parquet files for historical data

## Prerequisites

Before you begin, ensure you have the following installed:
- **Docker**: Version 26.x or higher
- **Docker Compose**: Version 2.x or higher

To verify your installations:
```bash
docker --version
docker-compose --version
```

## Project Structure

```
hft-lakehouse/
├── apps/
│   ├── ingestion-client/      # Go application for data ingestion
│   └── processing-job/        # Python scripts for data processing
├── dags/                      # Airflow DAGs
├── data/
│   └── cold_storage/          # Parquet files for cold storage
├── scripts/                   # Support and benchmark scripts
├── docker-compose.yml         # Docker services configuration
├── .env.example              # Environment variables template
└── README.md                 # This file
```

## Setup and Installation

### 1. Clone the Repository

```bash
git clone <repository-url>
cd hft-lakehouse
```

### 2. Configure Environment Variables

Copy the example environment file and update it with your configuration:

```bash
cp .env.example .env
```

Edit `.env` file to customize:
- Redis port and configuration
- TimescaleDB credentials and connection settings

### 3. Start the Environment

Start all services using Docker Compose:

```bash
docker-compose up -d
```

This will start:
- Redis (port 6379)
- TimescaleDB (port 5432)
- Ingestion Client (placeholder)

### 4. Verify Services are Running

Check service status:

```bash
docker-compose ps
```

All services should show as "healthy" or "running".

You can also use the test script:

```bash
bash test-docker.sh
```

## Service Details

### Redis
- **Image**: redis:7-alpine
- **Port**: 6379 (configurable via `REDIS_PORT`)
- **Purpose**: Hot storage for latest tick data and caching
- **Health Check**: `redis-cli ping`

### TimescaleDB
- **Image**: timescale/timescaledb:2.14.2-pg16
- **Port**: 5432 (configurable via `TIMESCALEDB_PORT`)
- **Purpose**: Time-series database for hot storage
- **Default Credentials**: postgres/postgres (change in .env)
- **Health Check**: `pg_isready`

### Ingestion Client
- **Status**: Placeholder (to be implemented)
- **Language**: Go
- **Purpose**: Real-time market data ingestion

## Common Commands

### Start services
```bash
docker-compose up -d
```

### Stop services
```bash
docker-compose down
```

### View logs
```bash
docker-compose logs -f
```

### View logs for specific service
```bash
docker-compose logs -f redis
docker-compose logs -f timescaledb
```

### Restart a service
```bash
docker-compose restart <service-name>
```

### Rebuild services
```bash
docker-compose up -d --build
```

## Troubleshooting

### Services fail to start
1. Ensure Docker Desktop is running
2. Check if ports 5432 and 6379 are not already in use
3. Review logs: `docker-compose logs`

### Permission errors
- On Linux/Mac, you may need to adjust permissions for data volumes
- Ensure your user has Docker permissions

### Connection issues
- Verify services are healthy: `docker-compose ps`
- Check network connectivity: `docker network inspect hft-lakehouse_hft-network`

## Development

### Running Tests
```bash
# Integration tests (to be implemented)
docker-compose -f docker-compose.test.yml up
```

### Accessing Databases

**Redis CLI:**
```bash
docker-compose exec redis redis-cli
```

**PostgreSQL (TimescaleDB):**
```bash
docker-compose exec timescaledb psql -U postgres -d hft_lakehouse
```

## Next Steps

- [ ] Implement Go ingestion client
- [ ] Implement Python processing job
- [ ] Set up Airflow DAGs
- [ ] Configure data pipelines

## License

[License information to be added]

## Contributing

[Contributing guidelines to be added]
