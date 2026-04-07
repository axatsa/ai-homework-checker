# Use an official Python runtime as a parent image
FROM python:3.11-slim

# Set environment variables for security and performance
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Set the working directory
WORKDIR /app

# Create a non-root user for security
RUN groupadd -r botuser && useradd -r -g botuser botuser

# Install system dependencies if needed
# We keep it minimal to reduce attack surface
RUN apt-get update && apt-get install -y --no-install-recommends \
    && rm -rf /var/lib/apt/lists/*

# Copy only requirements first to leverage Docker cache
COPY requirements.txt .

# Install python dependencies
RUN pip install -r requirements.txt

# Copy the rest of the application code
COPY . .

# Change ownership of the app directory to the non-root user
RUN chown -R botuser:botuser /app

# Switch to the non-root user
USER botuser

# Command to run the bot
CMD ["python", "bot.py"]
