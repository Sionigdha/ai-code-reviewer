# Use official Python image
FROM python:3.12-slim

# Set working directory inside the container
WORKDIR /app

# Copy requirements first (for faster builds)
COPY requirements.txt .

# Install all libraries
RUN pip install --no-cache-dir -r requirements.txt

# Copy all project files
COPY . .

# Tell Railway which port to use
EXPOSE 8000

# Command to start the server
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]