#!/bin/sh
python3 ./fetch_olympics_data.py --comp OG2024 --event FBLMTEAM11 --lang ENG --insecure
python3 ./assemble_api_response.py --comp OG2024 --event FBLMTEAM11 --lang ENG --tmp tmp --out $1
