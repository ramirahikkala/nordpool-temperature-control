FROM python:3.12-slim

WORKDIR /app

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Copy project files
COPY pyproject.toml .
COPY main.py .

# Install dependencies
RUN uv sync --frozen

# Run the temperature control script
CMD ["uv", "run", "main.py"]
