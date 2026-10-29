FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml ./
COPY src ./src
RUN pip install --no-cache-dir .
RUN useradd --system --uid 10001 app
USER app
EXPOSE {{port}}
CMD ["uvicorn", "{{name_snake}}.main:app", "--host", "0.0.0.0", "--port", "{{port}}"]
