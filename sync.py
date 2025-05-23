import os
import sys
import json
import time
import logging
import requests
import pyodbc
from datetime import datetime, date
from decimal import Decimal


# Custom JSON encoder to handle Decimal objects and date objects
class DecimalEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, Decimal):
            return float(obj)
        elif isinstance(obj, date):
            return obj.isoformat()  # Convert date to ISO format string (YYYY-MM-DD)
        elif isinstance(obj, datetime):
            return obj.isoformat()  # Convert datetime to ISO format string
        return super(DecimalEncoder, self).default(obj)


# Setup logging with better formatting
logging.basicConfig(
    level=logging.INFO,
    format='%(message)s',  # Simplified format for command prompt
    handlers=[
        # Overwrite log file each time
        logging.FileHandler('sync.log', mode='w'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

CONFIG_FILE = 'config.json'


def print_header():
    """Print a nice header for the application"""
    print("\n" + "=" * 70)
    print("              🚀 OMEGA DATABASE SYNC TOOL 🚀")
    print("=" * 70)
    print(f"Started at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 70 + "\n")


def print_progress_bar(current, total, prefix='Progress', bar_length=40):
    """Print a progress bar"""
    percent = float(current) * 100 / total
    filled_length = int(bar_length * current // total)
    bar = '█' * filled_length + '-' * (bar_length - filled_length)
    print(f'\r{prefix}: |{bar}| {percent:.1f}% ({current}/{total})',
          end='', flush=True)
    if current == total:
        print()  # New line when complete


def load_config():
    """Load configuration from config.json file"""
    try:
        print("📋 Loading configuration file...")
        with open(CONFIG_FILE, 'r') as f:
            config = json.load(f)
        print("✅ Configuration loaded successfully\n")
        return config
    except FileNotFoundError:
        print(f"❌ ERROR: Configuration file '{CONFIG_FILE}' not found!")
        print("   Please ensure config.json exists in the same folder.")
        input("\nPress Enter to exit...")
        sys.exit(1)
    except json.JSONDecodeError:
        print(f"❌ ERROR: Invalid JSON format in '{CONFIG_FILE}'!")
        print("   Please check your configuration file syntax.")
        input("\nPress Enter to exit...")
        sys.exit(1)


def connect_to_database(config):
    """Connect to SQL Anywhere database using ODBC"""
    try:
        print("🔌 Connecting to database...")
        dsn = config['database']['dsn']
        username = config['database']['username']
        password = config['database']['password']

        print(f"   → DSN: {dsn}")
        print(f"   → User: {username}")

        conn_str = f"DSN={dsn};UID={username};PWD={password}"
        conn = pyodbc.connect(conn_str)

        print("✅ Database connection successful!\n")
        return conn
    except pyodbc.Error as e:
        print(f"❌ Database connection failed!")
        print(f"   Error: {e}")
        print("   Please check your database configuration and ensure:")
        print("   • Database server is running")
        print("   • DSN is configured correctly")
        print("   • Username and password are correct")
        input("\nPress Enter to exit...")
        sys.exit(1)


def execute_query(conn, query):
    """Execute SQL query and return results as a list of dictionaries"""
    try:
        cursor = conn.cursor()
        cursor.execute(query)
        columns = [column[0] for column in cursor.description]
        results = []
        for row in cursor.fetchall():
            results.append(dict(zip(columns, row)))
        cursor.close()
        return results
    except pyodbc.Error as e:
        print(f"❌ Query execution failed: {e}")
        return []


def fetch_data(conn):
    """Fetch data from all required tables"""
    print("📊 FETCHING DATA FROM DATABASE")
    print("-" * 50)

    data = {}

    # Queries to fetch table
    tables = [
        ("acc_product", 'SELECT "code", "name", COALESCE("quantity", 0) + COALESCE("openingquantity", 0) AS quantity, "stockcatagory", "unit", "product", "brand", "billedcost", "basicprice", "partqty" FROM "acc_product"'),
        
        ("acc_invmast", 'SELECT "invdate", "slno" FROM "acc_invmast"'),
        
        ("acc_invdetails", 'SELECT "invno", "code", "quantity" FROM "acc_invdetails"'),
        
        ("acc_purchasemaster", 'SELECT "slno", "date", "pdate" FROM "acc_purchasemaster"'),
        
        ("acc_purchasedetails", 'SELECT "billno", "code", "quantity" FROM "acc_purchasedetails"'),
        
        ("acc_production", 'SELECT "productionno", "date" FROM "acc_production"'),
        
        ("acc_productiondetails", 'SELECT "masterno", "code", "qty" FROM "acc_productiondetails"'),
    ]



    total_records = 0

    for i, (table_name, query) in enumerate(tables, 1):
        print(f"{i}. Fetching {table_name}...", end=" ", flush=True)

        results = execute_query(conn, query)
        data[table_name] = results

        print(f"✅ {len(results):,} records")
        total_records += len(results)

    print("-" * 50)
    print(f"📈 TOTAL RECORDS TO SYNC: {total_records:,}")
    print()

    return data


def sync_data_to_api(data, config):
    """Sync data to the API server using the /api/sync endpoint"""
    try:
        api_base_url = config['api']['url']

        print(f"🌐 API Server: {api_base_url}")
        print()

        headers = {
            'Content-Type': 'application/json'
        }

        # API endpoint 
        sync_endpoint = f"{api_base_url}/api/sync"

        # Tables to sync 
        tables_to_sync = ["acc_product", "acc_invmast", "acc_invdetails", "acc_purchasemaster", "acc_purchasedetails", "acc_production", "acc_productiondetails"]

        print("📤 SYNCING DATA TO API")
        print("-" * 50)

        # Using batch size from your Node.js config
        def chunk_data(data_list, chunk_size=1000):
            for i in range(0, len(data_list), chunk_size):
                yield data_list[i:i + chunk_size]

        for table_index, table_name in enumerate(tables_to_sync, 1):
            if table_name in data:
                table_data = data[table_name]
                if not table_data:
                    print(f"{table_index}. {table_name}: No data to sync")
                    continue

                print(
                    f"{table_index}. Syncing {len(table_data):,} records from {table_name}...")

                chunks = list(chunk_data(table_data, chunk_size=1000))

                for chunk_index, chunk in enumerate(chunks, 1):
                    print_progress_bar(
                        chunk_index - 1, len(chunks), f"   Batch {chunk_index}/{len(chunks)}")

                    # Prepare payload for Django REST API
                    payload = {
                        # Default database name
                        "database": config.get('target_database', 'OMEGA'),
                        "table": table_name,
                        "data": chunk
                    }

                    success = False
                    for retry in range(3):  # 3 retries
                        try:
                            response = requests.post(
                                sync_endpoint,
                                data=json.dumps(payload, cls=DecimalEncoder),
                                headers=headers,
                                timeout=180  # 3 minutes timeout
                            )

                            if response.status_code == 200:
                                response_data = response.json()
                                if response_data.get('success', False):
                                    success = True
                                    break
                                else:
                                    print(
                                        f"\n   ⚠️  API Error: {response_data.get('error', 'Unknown error')}")
                                    if 'validation_errors' in response_data:
                                        # Show first 2 errors
                                        print(
                                            f"   📋 Validation errors: {response_data['validation_errors'][:2]}")
                            else:
                                print(
                                    f"\n   ⚠️  Retry {retry + 1}/3 (Status: {response.status_code})")
                                try:
                                    error_data = response.json()
                                    print(f"   📋 Error details: {error_data}")
                                except:
                                    # First 200
                                    print(
                                        f"   📋 Response text: {response.text[:200]}")
                                time.sleep(2)

                        except Exception as e:
                            print(
                                f"\n   ⚠️  Retry {retry + 1}/3 (Error: {str(e)})")
                            time.sleep(2)

                    print_progress_bar(chunk_index, len(
                        chunks), f"   Batch {chunk_index}/{len(chunks)}")

                    if not success:
                        print(
                            f"\n❌ Failed to sync {table_name} after 3 attempts")
                        return False

                print(f"   ✅ {table_name} synced successfully!")
                print()

        return True

    except Exception as e:
        print(f"❌ Sync Error: {str(e)}")
        return False


def main():
    """Main function to run the sync process"""
    try:
        print_header()

        # Load configuration
        config = load_config()

        # Connect to database
        conn = connect_to_database(config)

        # Fetch data
        data = fetch_data(conn)

        # Sync data to API
        success = sync_data_to_api(data, config)

        # Close connection
        conn.close()
        print("🔌 Database connection closed")
        print()

        if success:
            print("=" * 70)
            print("           🎉 SYNC COMPLETED SUCCESSFULLY! 🎉")
            print("=" * 70)
            print("✅ All data has been synchronized to the API server")
            print(
                f"✅ Completed at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            print("=" * 70)
            print()
            print("This window will close automatically in 5 seconds...")

            for i in range(5, 0, -1):
                print(f"Closing in {i}...", end="\r", flush=True)
                time.sleep(1)
            sys.exit(0)
        else:
            print("=" * 70)
            print("            ❌ SYNC FAILED! ❌")
            print("=" * 70)
            print("Please check the errors above and try again.")
            print("Common solutions:")
            print("• Check internet connection")
            print("• Verify API server is running")
            print("• Check configuration settings")
            print("• Verify credentials are correct")
            print("=" * 70)
            print()
            input("Press Enter to close...")
            sys.exit(1)

    except KeyboardInterrupt:
        print("\n\n⚠️  Sync cancelled by user")
        input("Press Enter to close...")
        sys.exit(1)
    except Exception as e:
        print("\n" + "=" * 70)
        print("            💥 UNEXPECTED ERROR! 💥")
        print("=" * 70)
        print(f"Error: {str(e)}")
        print("\nPlease contact technical support with this error message.")
        print("=" * 70)
        input("\nPress Enter to close...")
        sys.exit(1)


if __name__ == "__main__":
    main()
