# Temporary File Storage API

A Dockerized FastAPI application for temporary file storage with:
- 5GB max file size
- 24-hour automatic expiration
- Distributed across multiple storage volumes

## Features

- File upload with automatic expiration
- File download and metadata retrieval
- Storage statistics monitoring
- Distributed across /storage, /storage2, /storage3

## Getting Started

### Prerequisites

- Docker
- Docker Compose

### Installation

1. Clone the repository:
   ```bash
   git clone https://github.com/yourusername/temp-file-api.git
   cd temp-file-api
   ```

2. Build and run the containers:
   ```bash
   docker-compose up -d --build
   ```

3. The API will be available at `http://localhost:8000`

### API Documentation

After starting the service, access the interactive docs at:
`http://localhost:8000/docs`

## Configuration

Environment variables:
- `MAX_FILE_SIZE`: Maximum file size in bytes (default: 5368709120 = 5GB)
- `DEFAULT_EXPIRY`: Default expiration time in seconds (default: 86400 = 24h)

## GitHub Actions Setup

This repository includes GitHub Actions to:
- Build and test the Docker image on push
- Push to Docker Hub on release

## License

MIT
