import os
import json
import requests
from random import randint
import subprocess
from cryptography.fernet import Fernet

SERVER_URL = "http://92.51.21.72:5000"
LIST_FILE = "list.txt"
KEY_FILE = "key.key"
ITERATION_SEND_INTERVAL = 1
TOTAL = 16777215
RANGE_HEX_LEN = 18

# Загрузка ключа шифрования
with open(KEY_FILE, 'rb') as kf:
    fernet = Fernet(kf.read())

def get_gpu_info():
    """Получаем список доступных GPU и их параметры"""
    try:
        result = subprocess.run(["./KeyHunt-Cuda.exe", "-l"], capture_output=True, text=True)
        if result.returncode != 0:
            print("[WARNING] Не удалось получить информацию о GPU, используем GPU 0 по умолчанию")
            return ["0"], ["2048,128"]
        
        # Парсим вывод команды keyhunt -l
        lines = result.stdout.split('\n')
        gpu_ids = []
        for line in lines:
            if "CUDA Device" in line:
                parts = line.split()
                gpu_id = parts[2].strip(':')
                gpu_ids.append(gpu_id)
        
        if not gpu_ids:
            print("[WARNING] Не найдено доступных GPU, используем GPU 0 по умолчанию")
            return ["0"], ["2048,128"]
        
        # Для каждой карты используем стандартные параметры 2048,128
        grid_sizes = ["2048,128"] * len(gpu_ids)
        return gpu_ids, grid_sizes
        
    except Exception as e:
        print(f"[ERROR] Ошибка при получении информации о GPU: {e}")
        return ["0"], ["2048,128"]

def build_keyhunt_command(hex_str, gpu_ids, grid_sizes):
    """Собираем команду для запуска KeyHunt с учетом всех GPU"""
    start = hex_str.ljust(RANGE_HEX_LEN, '0')
    end = ':' + hex_str.ljust(RANGE_HEX_LEN, 'f')
    final_range = start + end
    
    base_cmd = [
        "./keyhunt",
        "-t", "0",  # Отключаем CPU
        "-g",       # Включаем GPU
        "-m", "address",
        "--coin", "BTC",
        "-o", "Found.txt",
        "--range", final_range,
        "1PWo3JeB9jrGwfHDNpdGK54CRas7fsVzXU"
    ]
    
    # Добавляем параметры GPU
    if len(gpu_ids) > 0:
        base_cmd.extend(["--gpui", ",".join(gpu_ids)])
    
    if len(grid_sizes) > 0:
        base_cmd.extend(["--gpux", ",".join(grid_sizes)])
    
    return base_cmd

def check_server_status():
    try:
        r = requests.get(f"{SERVER_URL}/status")
        status = r.json()
        if status.get("found"):
            print("[INFO] Сервер уже нашёл решение. Работа завершена.")
            exit(0)
    except Exception as e:
        print(f"[ERROR] Не удалось получить статус сервера: {e}")

def load_local_list():
    if not os.path.exists(LIST_FILE):
        return set()
    with open(LIST_FILE, 'r') as f:
        return set(f.read().split())

def save_local_list(data_set):
    with open(LIST_FILE, 'w') as f:
        f.write(' '.join(sorted(data_set)) + ' ')

def fetch_server_list():
    try:
        r = requests.get(f"{SERVER_URL}/list")
        decrypted = fernet.decrypt(r.content)
        return set(json.loads(decrypted.decode()))
    except Exception as e:
        print(f"[ERROR] Ошибка при получении списка с сервера: {e}")
        return set()

def send_new_data_to_server(new_data):
    if not new_data:
        return []
    payload = json.dumps({"data": list(new_data)}).encode()
    encrypted = fernet.encrypt(payload)
    try:
        r = requests.post(f"{SERVER_URL}/add", data=encrypted)
        response = json.loads(fernet.decrypt(r.content).decode())
        return response.get("added", [])
    except Exception as e:
        print(f"[ERROR] Не удалось отправить новые данные: {e}")
        return []

def count_spaces():
    if not os.path.exists(LIST_FILE):
        return 0
    with open(LIST_FILE, 'r') as f:
        return f.read().count(' ')

def check_and_send_found():
    if os.path.exists("Found.txt"):
        try:
            with open("Found.txt", "r") as f:
                found_lines = list(set(line.strip() for line in f if line.strip()))
            payload = json.dumps({"found": found_lines}).encode()
            encrypted = fernet.encrypt(payload)
            r = requests.post(f"{SERVER_URL}/found", data=encrypted)
            if r.status_code == 200:
                print("[INFO] связь с сервером")
                os.remove("Found.txt")
            else:
                print(f"[ERROR] Сервер вернул ошибку: {r.status_code}")
        except Exception as e:
            print(f"[ERROR] Не удалось отправить Found.txt: {e}")

# Инициализация
iteration = 0
local_data = load_local_list()
gpu_ids, grid_sizes = get_gpu_info()
print(f"[INFO] Используем GPU: {gpu_ids} с параметрами: {grid_sizes}")

while True:
    check_server_status()
    check_and_send_found()

    iteration += 1

    rand = randint(0x40000000, 0x7fffffff)
    hex_str = hex(rand)[2:]

    if hex_str not in local_data:
        # Собираем команду с учетом всех GPU
        command = build_keyhunt_command(hex_str, gpu_ids, grid_sizes)
        print(f"[INFO] Запускаем команду: {' '.join(command)}")

        # Запуск KeyHunt
        process = subprocess.run(command)

        # Только после успешного выполнения KeyHunt
        if process.returncode == 0:
            local_data.add(hex_str)
            save_local_list(local_data)
            progress = count_spaces() / TOTAL
            print(f"Прогресс: {progress:.2%}")
        else:
            print(f"[ERROR] KeyHunt завершился с кодом {process.returncode}")

    # Синхронизация с сервером
    if iteration % ITERATION_SEND_INTERVAL == 0:
        server_data = fetch_server_list()
        new_for_server = local_data - server_data
        send_new_data_to_server(new_for_server)

        new_from_server = server_data - local_data
        if new_from_server:
            local_data.update(new_from_server)
            save_local_list(local_data)