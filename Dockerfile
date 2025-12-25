FROM python:3.12-slim

WORKDIR /app

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Copy project files
COPY pyproject.toml uv.lock .
COPY main.py .
COPY web_app.py .
COPY heating_logger.py .
COPY templates/ templates/

# Install dependencies
RUN uv sync --frozen

# Run the temperature control script
CMD ["uv", "run", "main.py"]
