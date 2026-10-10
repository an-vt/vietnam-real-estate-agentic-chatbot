# Production deployment

This deployment runs the frontend build, Nginx, and backend on one EC2
instance with Docker Compose. PostgreSQL runs on Amazon RDS; it is not included
in Compose.

## EC2 setup

Clone the repository on the EC2 instance and install Docker Engine, the Docker
Compose plugin, and Git. The EC2 security group should allow HTTP port 80 from
the intended clients and SSH only from an administrator IP. The RDS security
group should allow PostgreSQL port 5432 only from the EC2 security group.

Create the application directory and pull the source:

```bash
git clone <github-repository-url> /opt/vietnam-real-estate
cd /opt/vietnam-real-estate
git pull
```

Create the production configuration:

```bash
cd /opt/vietnam-real-estate/infra/production
cp .env.example .env
${EDITOR:-vi} .env
```

Create the Docker secret files. Do not commit these files:

```bash
install -m 600 /dev/null secrets/postgres_password
install -m 600 /dev/null secrets/llm_api_key
${EDITOR:-vi} secrets/postgres_password
${EDITOR:-vi} secrets/llm_api_key
```

The RDS database must support the `vector` extension. The first migration
creates the schema and extension, and the second creates the HNSW index.

## Start the application

```bash
cd /opt/vietnam-real-estate/infra/production
make up
make logs
```

The frontend build service writes static files to a named Docker volume. The
separate Nginx service serves that volume, publishes port 80, and proxies `/api`
to the private backend container. Frontend, backend, and Nginx share the
explicit Docker network `vietnam-real-estate-chatbot-net`; the backend is not
published directly on the EC2 host.

## Import listings

Copy the CSV to the EC2 path configured by `CSV_PATH`, then run:

```bash
make ingest
```

The importer deduplicates by listing ID, keeps the newest scrape, includes
price in the embedding text, uses token-aware batches, and resumes safely.
Use `make ingest FORCE=1` only when all embeddings must be regenerated.

## Update the application

```bash
cd /opt/vietnam-real-estate
git pull
cd infra/production
make up
```
