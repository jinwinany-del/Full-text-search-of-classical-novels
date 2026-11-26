FROM python:3.12-slim

WORKDIR /app

COPY library.py server.py accounts.py backup_users_db.py ./
COPY static ./static
COPY licenses ./licenses
COPY THIRD_PARTY_NOTICES.txt ./
COPY data ./data

EXPOSE 8000

CMD ["python", "server.py", "8000"]
