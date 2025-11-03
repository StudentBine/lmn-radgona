import database
from werkzeug.security import check_password_hash

# Test login manually
username = 'admin'
password = 'admin123'

user = database.get_admin_user(username)
print(f"User found: {user is not None}")

if user:
    print(f"Username: {user['username']}")
    print(f"Password hash: {user['password'][:50]}...")
    print(f"Permissions: {user['permissions']}")
    
    password_check = check_password_hash(user['password'], password)
    print(f"Password correct: {password_check}")
    
    if password_check:
        print("Login would be successful!")
    else:
        print("Password check failed")
else:
    print("User not found!")