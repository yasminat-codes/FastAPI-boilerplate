# FastAPI Template

<p align="center">
  <img src="assets/FastAPI-boilerplate.png" alt="Rocket illustration for the FastAPI template." width="35%" height="auto">
</p>

<p align="center">
  <i>A reusable FastAPI backend template with production-ready defaults.</i>
</p>

!!! note "Template customization"
    If you cloned this repository for a new product, replace the default repository metadata, package name, support links, and docs branding before publishing your derived project internally or externally.

<p align="center">
  <a href="https://fastapi.tiangolo.com">
      <img src="https://img.shields.io/badge/FastAPI-005571?style=for-the-badge&logo=fastapi" alt="FastAPI">
  </a>
  <a href="https://docs.pydantic.dev/2.4/">
      <img src="https://img.shields.io/badge/Pydantic-E92063?logo=pydantic&logoColor=fff&style=for-the-badge" alt="Pydantic">
  </a>
  <a href="https://www.postgresql.org">
      <img src="https://img.shields.io/badge/PostgreSQL-316192?style=for-the-badge&logo=postgresql&logoColor=white" alt="PostgreSQL">
  </a>
  <a href="https://redis.io">
      <img src="https://img.shields.io/badge/Redis-DC382D?logo=redis&logoColor=fff&style=for-the-badge" alt="Redis">
  </a>
  <a href="https://docs.docker.com/compose/">
      <img src="https://img.shields.io/badge/Docker-2496ED?logo=docker&logoColor=fff&style=for-the-badge" alt="Docker">
  </a>
</p>

## What is FastAPI Template?

FastAPI Template is a production-ready backend foundation for teams that want a strong FastAPI starting point without inheriting client-specific code. It combines hardened platform primitives with clear extension points for domain logic, integrations, webhooks, workflows, and operations.

## Repository Identity

The source repository should be presented as `FastAPI Template` and kept generically branded under the package baseline `fastapi-template`. Its intended GitHub positioning is a reusable template repository: teams should create a derived repository via **Use this template**, then replace the default metadata, branding, and support ownership in the copy they publish.

## Core Technologies

This template uses modern Python infrastructure and keeps the defaults close to production:

- **[FastAPI](https://fastapi.tiangolo.com)** - Modern, fast web framework for building APIs with Python 3.7+
- **[Pydantic V2](https://docs.pydantic.dev/2.4/)** - Data validation and settings management
- **[SQLAlchemy 2.0](https://docs.sqlalchemy.org/en/20/)** - Python SQL toolkit and Object Relational Mapper
- **[PostgreSQL](https://www.postgresql.org)** - Advanced open source relational database
- **[Redis](https://redis.io)** - In-memory data store for caching and message brokering
- **[ARQ](https://arq-docs.helpmanual.io)** - Job queues and RPC with asyncio and Redis
- **[Docker](https://docs.docker.com/compose/)** - Containerization for easy deployment
- **[NGINX](https://nginx.org/en/)** - High-performance web server for reverse proxy and load balancing

## Key Features

### Performance & Scalability
- Fully async architecture
- Pydantic V2 for ultra-fast data validation
- SQLAlchemy 2.0 with efficient query patterns
- Built-in caching with Redis
- Horizontal scaling with NGINX load balancing

### Security & Authentication
- JWT-based authentication with refresh tokens
- Cookie-based secure token storage
- Role-based access control with user tiers
- Rate limiting to prevent abuse
- Production-ready security configurations

### Developer Experience
- Comprehensive CRUD operations with [FastCRUD](https://github.com/igorbenav/fastcrud)
- Automatic API documentation
- Database migrations with Alembic
- Background task processing
- Extensive test coverage
- Docker Compose for easy development

### Production Ready
- Environment-based configuration
- Structured logging
- Health checks and monitoring
- NGINX reverse proxy setup
- Gunicorn with Uvicorn workers
- Database connection pooling

## Quick Start

Get up and running with your own derived repository:

```bash
# Clone your template-derived repository
git clone https://github.com/<your-org>/<your-repo>
cd <your-repo>

# Start with Docker Compose
docker compose up
```

That's it! Your API will be available at `http://localhost:8000/docs`

**[Continue with the Getting Started Guide →](getting-started/index.md)**

## Documentation Structure

### For New Users
- **[Getting Started](getting-started/index.md)** - Quick setup and first steps
- **[User Guide](user-guide/index.md)** - Comprehensive feature documentation

### For Developers
- **[Development](user-guide/development.md)** - Extending and customizing the template
- **[Testing](user-guide/testing.md)** - Testing strategies and best practices
- **[Production](user-guide/production.md)** - Production deployment guides

## Perfect For

- **REST APIs** - Build robust, scalable REST APIs
- **Microservices** - Create microservice architectures
- **SaaS Applications** - Multi-tenant applications with user tiers
- **Data APIs** - APIs for data processing and analytics

## Support & Maintenance

- **[Support guide](community.md)** - Decide how maintainers, adopters, and contributors should collaborate
- **Your repository issue tracker** - Use the issue templates configured in the repo you cloned
