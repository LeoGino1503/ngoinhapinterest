docker stop $(docker ps -q)
docker compose up -d
source .venv/bin/activate
python -m pip install --upgrade pip setuptools wheel
pip install -r requirements.txt
python -m uvicorn main:app --host 0.0.0.0 --port 8080 --reload