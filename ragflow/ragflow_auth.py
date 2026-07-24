from __future__ import annotations

import os
import subprocess


TENANT_ID = "e12d982e828711f1b28a8183acf060e9"
RAGFLOW_CONTAINER = os.getenv("RAGFLOW_CONTAINER", "docker-ragflow-cpu-1")


def get_api_key() -> str:
    api_key = os.getenv("RAGFLOW_API_KEY", "").strip()
    if api_key:
        return api_key

    command = [
        "docker",
        "exec",
        RAGFLOW_CONTAINER,
        "python",
        "-c",
        (
            "import os,pymysql; "
            "conn=pymysql.connect(host=os.getenv('MYSQL_HOST'),"
            "port=int(os.getenv('MYSQL_PORT','3306')),"
            "user='root',password=os.getenv('MYSQL_PASSWORD'),"
            "database=os.getenv('MYSQL_DBNAME'),charset='utf8mb4'); "
            "cur=conn.cursor(); "
            "cur.execute('select token from api_token where tenant_id=%s order by create_time desc limit 1', "
            f"('{TENANT_ID}',)); "
            "row=cur.fetchone(); "
            "print(row[0] if row else '')"
        ),
    ]
    result = subprocess.run(command, check=True, capture_output=True, text=True)
    api_key = result.stdout.strip()
    if not api_key:
        raise SystemExit("No RAGFlow API token found. Please create an API token in RAGFlow first.")
    return api_key
