import database

# Check tables
conn = database.get_db_connection()
cursor = conn.cursor()
cursor.execute("SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'")
tables = cursor.fetchall()
print('Tables:', [t['table_name'] for t in tables])

# Check admin_users table structure
cursor.execute("SELECT column_name, data_type FROM information_schema.columns WHERE table_name = 'admin_users'")
columns = cursor.fetchall()
print('Admin users columns:', [(c['column_name'], c['data_type']) for c in columns])

# Try to manually create admin user
try:
    from werkzeug.security import generate_password_hash
    password_hash = generate_password_hash('admin123')
    permissions = ['manage_users', 'manage_teams', 'manage_players', 'manage_results', 'manage_cards', 'view_statistics']
    
    cursor.execute("INSERT INTO admin_users (username, password, permissions) VALUES (%s, %s, %s) RETURNING id", 
                   ('admin', password_hash, permissions))
    user_id = cursor.fetchone()['id']
    conn.commit()
    print(f"Created admin user with ID: {user_id}")
except Exception as e:
    print(f"Error creating admin user: {e}")

database.release_db_connection(conn)