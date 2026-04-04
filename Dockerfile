FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir --timeout=300 --retries=5 -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple/

COPY . .

EXPOSE 8501

CMD ["python", "-m", "streamlit", "run", "ui.py", "--server.address=0.0.0.0", "--server.port=8501"]