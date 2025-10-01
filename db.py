from sqlite3 import connect, Connection, Cursor

from werkzeug.security import generate_password_hash, check_password_hash

class Database:
    def __init__(self, db_name: str):
        self.connection: Connection = connect(db_name)
        self.cursor: Cursor = self.connection.cursor()

        self._create_tables()

    def _create_tables(self):
        self.cursor.executescript('''
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                password TEXT NOT NULL,
                status TEXT DEFAULT 'user'
            );
                                  
            CREATE TABLE IF NOT EXISTS chats (
                id INTEGER PRIMARY KEY,
                admin_id INTEGER,
                name TEXT NOT NULL
            );
                                  
            CREATE TABLE IF NOT EXISTS channels (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                admin_id INTEGER,
                                  
                FOREIGN KEY(admin_id) REFERENCES users(id)
            );
                                  
            CREATE TABLE IF NOT EXISTS chat_members (
                id INTEGER PRIMARY KEY,
                chat_id INTEGER,
                user_id INTEGER,
                                  
                FOREIGN KEY(chat_id) REFERENCES chats(id),
                FOREIGN KEY(user_id) REFERENCES users(id)
            );
            
            CREATE TABLE IF NOT EXISTS personal_messages (
                id INTEGER PRIMARY KEY,
                sender_id INTEGER,
                to_user_id INTEGER,
                content TEXT NOT NULL,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                            
                FOREIGN KEY(sender_id) REFERENCES users(id),
                FOREIGN KEY(to_user_id) REFERENCES users(id)
            );
                                  
            CREATE TABLE IF NOT EXISTS chat_messages (
                id INTEGER PRIMARY KEY,
                chat_id INTEGER,
                sender_id INTEGER,
                content TEXT NOT NULL,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                                  
                FOREIGN KEY(chat_id) REFERENCES chats(id),
                FOREIGN KEY(sender_id) REFERENCES users(id)
            );
                                  
            CREATE TABLE IF NOT EXISTS channel_messages (
                id INTEGER PRIMARY KEY,
                channel_id INTEGER,
                sender_id INTEGER,
                content TEXT NOT NULL,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                                  
                FOREIGN KEY(channel_id) REFERENCES channels(id),
                FOREIGN KEY(sender_id) REFERENCES users(id)
            );
        ''')
        self.connection.commit()

    def signup(self, name: str, password: str, password2: str):
        hashed_password = generate_password_hash(password)
        if name in self.get_all_usernames():
            return 'Username already exists'
        if len(password) < 4:
            return 'Password must be at least 4 characters long'
        if password != password2:
            return 'Passwords do not match'
        self.cursor.execute('''
                            INSERT INTO users (name, password, status) VALUES (?, ?, ?)
                            ''', (name, hashed_password, "user"))
        self.connection.commit()
        return True

    def signin(self, name: str, password: str):
        if name == '' or password == '':
            return 'Username and password cannot be empty'
        if name not in self.get_all_usernames():
            return 'Username does not exist'
        
        self.cursor.execute('''
                            SELECT password FROM users WHERE name = ?
                            ''', (name,))
        row = self.cursor.fetchone()
        if not row:
            return 'Username does not exist'
        hashed = row[0]
        if not check_password_hash(hashed, password):
            return 'Incorrect password'
        return True
    
    def create_chat(self, admin_id: int, name: str):
        self.cursor.execute('''
                            INSERT INTO chats (admin_id, name) VALUES (?, ?)
                            ''', (admin_id, name))
        self.connection.commit()
        return self.cursor.lastrowid
    
    def create_channel(self, admin_id: int, name: str):
        self.cursor.execute('''
                            INSERT INTO channels (name, admin_id) VALUES (?, ?)
                            ''', (name, admin_id))
        self.connection.commit()
        return self.cursor.lastrowid
    
    def add_user_to_chat(self, chat_id: int, user_id: int):
        self.cursor.execute('''
                            INSERT INTO chat_members (chat_id, user_id) VALUES (?, ?)
                            ''', (chat_id, user_id))
        self.connection.commit()
        return self.cursor.lastrowid

    def is_user_chat_member(self, chat_id: int, user_id: int) -> bool:
        self.cursor.execute('''
            SELECT 1 FROM chat_members WHERE chat_id = ? AND user_id = ?
        ''', (chat_id, user_id))
        return self.cursor.fetchone() is not None

    def close(self):
        self.connection.close()

    def check_user_exists(self, name: str) -> bool:
        self.cursor.execute('''
                            SELECT 1 FROM users WHERE name = ?
                            ''', (name,))
        return self.cursor.fetchone() is not None
    
    def create_personal_message(self, sender_id: int, to_user_id: int, content: str):
        self.cursor.execute('''
                            INSERT INTO personal_messages (sender_id, to_user_id, content) VALUES (?, ?, ?)
                            ''', (sender_id, to_user_id, content))
        self.connection.commit()
        return self.cursor.lastrowid
    
    def get_personal_messages(self, user1_id: int, user2_id: int):
        self.cursor.execute('''
            SELECT id, sender_id, content, timestamp
            FROM personal_messages
            WHERE (sender_id = ? AND to_user_id = ?)
            OR (sender_id = ? AND to_user_id = ?)
            ORDER BY timestamp ASC
        ''', (user1_id, user2_id, user2_id, user1_id))
        return self.cursor.fetchall()

    def delete_personal_message(self, message_id: int, owner_id: int) -> bool:
        self.cursor.execute('''
            DELETE FROM personal_messages WHERE id = ? AND sender_id = ?
        ''', (message_id, owner_id))
        self.connection.commit()
        return self.cursor.rowcount > 0
    
    def get_all_users(self):
        self.cursor.execute('''
            SELECT id, name FROM users
        ''')
        return self.cursor.fetchall()

    def get_all_channels(self):
        self.cursor.execute('''
            SELECT id, name FROM channels
        ''')
        return self.cursor.fetchall()

    def get_owned_channel_ids(self, user_id: int):
        self.cursor.execute('''
            SELECT id FROM channels WHERE admin_id = ?
        ''', (user_id,))
        return {row[0] for row in self.cursor.fetchall()}
    
    def get_all_chats_where_user_is_member(self, user_id: int):
        self.cursor.execute('''
            SELECT c.id, c.name
            FROM chats c
            JOIN chat_members cm ON c.id = cm.chat_id
            WHERE cm.user_id = ?
        ''', (user_id,))
        return self.cursor.fetchall()

    def get_owned_chat_ids(self, user_id: int):
        self.cursor.execute('''
            SELECT id FROM chats WHERE admin_id = ?
        ''', (user_id,))
        return {row[0] for row in self.cursor.fetchall()}
    
    def get_all_usernames(self):
        self.cursor.execute('''
            SELECT name FROM users
        ''')
        return [row[0] for row in self.cursor.fetchall()]
    
    def get_user_id(self, name: str):
        self.cursor.execute('''
            SELECT id FROM users WHERE name = ?
        ''', (name,))
        result = self.cursor.fetchone()
        return result[0] if result else None

    def get_username(self, user_id: int):
        self.cursor.execute('''
            SELECT name FROM users WHERE id = ?
        ''', (user_id,))
        result = self.cursor.fetchone()
        return result[0] if result else None

    def get_chat_name(self, chat_id: int):
        self.cursor.execute('''
            SELECT name FROM chats WHERE id = ?
        ''', (chat_id,))
        row = self.cursor.fetchone()
        return row[0] if row else None

    def get_channel_name(self, channel_id: int):
        self.cursor.execute('''
            SELECT name FROM channels WHERE id = ?
        ''', (channel_id,))
        row = self.cursor.fetchone()
        return row[0] if row else None
    
    def get_channel_messages(self, channel_id: int):
        self.cursor.execute('''
            SELECT cm.id, cm.sender_id, cm.content, cm.timestamp, u.name
            FROM channel_messages cm
            JOIN users u ON cm.sender_id = u.id
            WHERE cm.channel_id = ?
            ORDER BY cm.timestamp ASC
        ''', (channel_id,))
        return self.cursor.fetchall()

    def create_channel_message(self, channel_id: int, sender_id: int, content: str):
        self.cursor.execute('''
            INSERT INTO channel_messages (channel_id, sender_id, content) VALUES (?, ?, ?)
        ''', (channel_id, sender_id, content))
        self.connection.commit()
        return self.cursor.lastrowid

    def delete_channel_message(self, message_id: int, owner_id: int) -> bool:
        self.cursor.execute('''
            DELETE FROM channel_messages WHERE id = ? AND sender_id = ?
        ''', (message_id, owner_id))
        self.connection.commit()
        return self.cursor.rowcount > 0
    
    def get_chat_messages(self, chat_id: int):
        self.cursor.execute('''
            SELECT cm.id, cm.sender_id, cm.content, cm.timestamp, u.name
            FROM chat_messages cm
            JOIN users u ON cm.sender_id = u.id
            WHERE cm.chat_id = ?
            ORDER BY cm.timestamp ASC
        ''', (chat_id,))
        return self.cursor.fetchall()

    def create_chat_message(self, chat_id: int, sender_id: int, content: str):
        self.cursor.execute('''
            INSERT INTO chat_messages (chat_id, sender_id, content) VALUES (?, ?, ?)
        ''', (chat_id, sender_id, content))
        self.connection.commit()
        return self.cursor.lastrowid
    
    def delete_chat_message(self, message_id: int, owner_id: int) -> bool:
        self.cursor.execute('''
            DELETE FROM chat_messages WHERE id = ? AND sender_id = ?
        ''', (message_id, owner_id))
        self.connection.commit()
        return self.cursor.rowcount > 0
    
    def get_chat_members(self, chat_id: int):
        self.cursor.execute('''
            SELECT u.id, u.name
            FROM chat_members cm
            JOIN users u ON cm.user_id = u.id
            WHERE cm.chat_id = ?
        ''', (chat_id,))
        return self.cursor.fetchall()
    
    def is_user_chat_admin(self, user_id: int, chat_id: int = None):
        self.cursor.execute('''
            SELECT admin_id FROM chats WHERE id = ?
        ''', (chat_id,))
        result = self.cursor.fetchone()
        return bool(result and result[0] == user_id)
        
    def is_user_channel_admin(self, user_id: int, channel_id: int):
        self.cursor.execute('''
            SELECT admin_id FROM channels WHERE id = ?
        ''', (channel_id,))
        result = self.cursor.fetchone()
        return bool(result and result[0] == user_id)

    def delete_chat(self, chat_id: int, owner_id: int) -> bool:
        if not self.is_user_chat_admin(owner_id, chat_id):
            return False
        self.cursor.execute('DELETE FROM chat_messages WHERE chat_id = ?', (chat_id,))
        self.cursor.execute('DELETE FROM chat_members WHERE chat_id = ?', (chat_id,))
        self.cursor.execute('DELETE FROM chats WHERE id = ?', (chat_id,))
        self.connection.commit()
        return self.cursor.rowcount > 0

    def delete_channel(self, channel_id: int, owner_id: int) -> bool:
        if not self.is_user_channel_admin(owner_id, channel_id):
            return False
        self.cursor.execute('DELETE FROM channel_messages WHERE channel_id = ?', (channel_id,))
        self.cursor.execute('DELETE FROM channels WHERE id = ?', (channel_id,))
        self.connection.commit()
        return self.cursor.rowcount > 0

    def get_channel_owner(self, channel_id: int):
        self.cursor.execute('''
            SELECT u.name
            FROM channels c
            JOIN users u ON c.admin_id = u.id
            WHERE c.id = ?
        ''', (channel_id,))
        row = self.cursor.fetchone()
        return row[0] if row else None

    def get_chat_online_members_count(self, chat_id: int, online_user_ids: set, exclude_user_id: int = None):
        self.cursor.execute('''
            SELECT user_id FROM chat_members WHERE chat_id = ?
        ''', (chat_id,))
        member_ids = {row[0] for row in self.cursor.fetchall()}
        online_ids = member_ids.intersection(online_user_ids)
        if exclude_user_id is not None and exclude_user_id in online_ids:
            online_ids.discard(exclude_user_id)
        online_count = len(online_ids)
        return online_count

    def update_chat_name(self, chat_id: int, new_name: str, admin_id: int) -> bool:
        if not self.is_user_chat_admin(admin_id, chat_id):
            return False
        self.cursor.execute('''
            UPDATE chats SET name = ? WHERE id = ?
        ''', (new_name, chat_id))
        self.connection.commit()
        return self.cursor.rowcount > 0
    
    def update_channel_name(self, channel_id: int, new_name: str, admin_id: int) -> bool:
        if not self.is_user_channel_admin(admin_id, channel_id):
            return False
        self.cursor.execute('''
            UPDATE channels SET name = ? WHERE id = ?
        ''', (new_name, channel_id))
        self.connection.commit()
        return self.cursor.rowcount > 0

if __name__ == '__main__':
    db = Database('db.db')
    db._create_tables()

    user1_id = db.signup('user1', 'password1')
    user2_id = db.signup('user2', 'password2')
    db.create_personal_message(user1_id, user2_id, 'Hello, user2!')
    db.create_personal_message(user2_id, user1_id, 'Hi, user1!')
    print(db.get_all_users())

    db.close()