FROM python:3.8.6-buster

RUN apt update
RUN apt install procinfo

WORKDIR /gatesbot

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .
CMD ["python", "dbot.py"]