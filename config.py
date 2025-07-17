import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    SECRET_KEY = os.getenv('SECRET_KEY') or 'your-secret-key-here'
    DB_SERVER = os.getenv('DB_SERVER') or 'DESKTOP-FDTP2UC\SQLEXPRESS'  # Updated
    DB_NAME = os.getenv('DB_NAME') or 'JobTrainingMonitoring'
    DB_DRIVER = os.getenv('DB_DRIVER') or 'SQL Server'