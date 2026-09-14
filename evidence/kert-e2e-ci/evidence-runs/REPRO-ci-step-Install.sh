pip install --upgrade pip
if [ -f requirements-lock.txt ]; then
  pip install -c requirements-lock.txt ".[api,dev]"
else
  pip install ".[api,dev]"
fi
