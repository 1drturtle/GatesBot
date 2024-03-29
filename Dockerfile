FROM python:3.11-slim

RUN apt update && apt install --no-install-recommends -y procinfo

WORKDIR /gatesbot

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .
CMD ["python", "dbot.py"]
