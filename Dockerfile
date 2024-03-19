FROM python:3.11-alpine

WORKDIR /gatesbot

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .
CMD ["python", "dbot.py"]
