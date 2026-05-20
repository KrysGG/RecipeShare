import mysql.connector
from mysql.connector import Error

DB_CONFIG = {
    "host": "localhost",
    "user": "root",
    "password": "",  # Asegúrate de que coincida con tu XAMPP
    "database": "recipeshare_db"
}


def get_connection():
    try:
        return mysql.connector.connect(**DB_CONFIG)
    except Error as err:
        print(f"Error conectando a MySQL: {err}")
        raise
