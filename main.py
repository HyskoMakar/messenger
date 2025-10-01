import os
from dotenv import load_dotenv
from flask import Flask, render_template, request, redirect, url_for, session, g
from flask_socketio import SocketIO, send, emit, join_room, leave_room

from db import Database

load_dotenv()

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'change-me')

sio = SocketIO(app, cors_allowed_origins="*")

ONLINE_USER_IDS = set()

def get_db():
    if 'db' not in g:
        db_path = os.environ.get('DATABASE_PATH', 'app.db')
        g.db = Database(db_path)
    return g.db

@app.teardown_appcontext
def close_db(error):
    db = g.pop('db', None)
    if db is not None:
        db.close()

# Socket.IO event handlers

@sio.on('connect')
def handle_connect():
    username = session.get('username')
    if not username:
        return False
    user_id = get_db().get_user_id(username)
    if user_id:
        ONLINE_USER_IDS.add(user_id)
        join_room(f'user:{user_id}')
        sio.emit('presence', {'user_id': user_id, 'online': True})
    emit('system', {'message': f'{username} connected'})

@sio.on('disconnect')
def handle_disconnect():
    username = session.get('username')
    if not username:
        return
    user_id = get_db().get_user_id(username)
    if user_id and user_id in ONLINE_USER_IDS:
        ONLINE_USER_IDS.discard(user_id)
        sio.emit('presence', {'user_id': user_id, 'online': False})

@sio.on('join')
def handle_join(data):
    room = data.get('room')
    if not room:
        return
    join_room(room)
    emit('system', {'message': 'joined room', 'room': room}, to=room)

@sio.on('leave')
def handle_leave(data):
    room = data.get('room')
    if not room:
        return
    leave_room(room)
    emit('system', {'message': 'left room', 'room': room}, to=room)
# Typing indicator (personal)
@sio.on('typing')
def handle_typing(data):
    username = session.get('username')
    if not username:
        return
    room = data.get('room')
    if not room:
        return
    user_id = get_db().get_user_id(username)
    # notify the chat room (if someone listens there)
    emit('typing', {'user_id': user_id}, to=room, include_self=False)
    # also notify recipient via their personal room for user list
    try:
        uid1_str, uid2_str = room.split(':')
        uid1 = int(uid1_str)
        uid2 = int(uid2_str)
    except Exception:
        return
    recipient_id = uid2 if user_id == uid1 else uid1
    sio.emit('typing_presence', {'user_id': user_id}, to=f'user:{recipient_id}')

@sio.on('delete_message')
def delete_message(data):
    username = session.get('username')
    if not username:
        return
    db = get_db()
    user_id = db.get_user_id(username)
    if not user_id:
        return

    scope = data.get('scope')
    try:
        msg_id = int(data.get('id') or data.get('message_id'))
    except (TypeError, ValueError):
        return

    if scope == 'personal':
        peer_id = data.get('peer_id')
        try:
            peer_id = int(peer_id)
        except (TypeError, ValueError):
            peer_id = None
        ok = db.delete_personal_message(msg_id, user_id)
        if ok:
            if peer_id:
                a, b = sorted([int(user_id), int(peer_id)])
                room = f"{a}:{b}"
                sio.emit('message_deleted', {'id': msg_id}, to=room)
            else:
                sio.emit('message_deleted', {'id': msg_id})

    # Chat message: emit to chat room "chat:{id}"
    elif scope == 'chat':
        chat_id = data.get('chat_id')
        try:
            chat_id_int = int(chat_id)
        except (TypeError, ValueError):
            return
        ok = db.delete_chat_message(msg_id, user_id)
        if ok:
            sio.emit('message_deleted', {'id': msg_id}, to=f"chat:{chat_id_int}")


    elif scope == 'channel':
        channel_id = data.get('channel_id')
        try:
            channel_id_int = int(channel_id)
        except (TypeError, ValueError):
            return
        ok = db.delete_channel_message(msg_id, user_id)
        if ok:
            sio.emit('message_deleted', {'id': msg_id}, to=f"channel:{channel_id_int}")

@sio.on('personal_message')
def personal_message(data):
    username = session.get('username')
    self_id = get_db().get_user_id(username)
    text = data.get('text')
    room = data.get('room')
    if not text or not username or not room:
        return

    user1, user2 = room.split(':')
    try:
        user1_id = int(user1)
        user2_id = int(user2)
    except ValueError:
        return

    other_user_id = user2_id if self_id == user1_id else user1_id

    db = get_db()
    message_id = db.create_personal_message(self_id, other_user_id, text)
    db.cursor.execute('SELECT timestamp FROM personal_messages WHERE id = ?', (message_id,))
    row = db.cursor.fetchone()
    ts = row[0] if row else None

    payload = {'id': message_id, 'username': username, 'text': text, 'ts': ts}
    emit('personal_message', payload, to=room)

@sio.on('chat_message')
def chat_message(data):
    username = session.get('username')
    user_id = get_db().get_user_id(username)
    text = data.get('text')
    chat_id = data.get('chat_id')
    if not text or not chat_id or not user_id:
        return
    try:
        chat_id = int(chat_id)
    except (TypeError, ValueError):
        return
    db = get_db()
    if not db.is_user_chat_member(chat_id, user_id):
        return
    message_id = db.create_chat_message(chat_id, user_id, text)
    db.cursor.execute('SELECT timestamp FROM chat_messages WHERE id = ?', (message_id,))
    row = db.cursor.fetchone()
    ts = row[0] if row else None
    emit('chat_message', {'id': message_id, 'username': username, 'text': text, 'ts': ts}, to=f"chat:{chat_id}")

@sio.on('channel_message')
def channel_message(data):
    username = session.get('username')
    user_id = get_db().get_user_id(username)
    text = data.get('text')
    channel_id = data.get('channel_id')
    if not text or not channel_id or not user_id:
        return
    try:
        channel_id = int(channel_id)
    except (TypeError, ValueError):
        return
    db = get_db()
    
    if not db.is_user_channel_admin(user_id, channel_id):
        return
    message_id = db.create_channel_message(channel_id, user_id, text)
    db.cursor.execute('SELECT timestamp FROM channel_messages WHERE id = ?', (message_id,))
    row = db.cursor.fetchone()
    ts = row[0] if row else None
    emit('channel_message', {'id': message_id, 'username': username, 'text': text, 'ts': ts}, to=f"channel:{channel_id}")

# Delete confirmation page and handler
@app.route('/confirm_delete', methods=['GET', 'POST'])
def confirm_delete():
    return redirect(url_for('home'))

# HTTP routes

@app.route('/', methods=['GET'])
def index():
    if 'username' in session:
        return redirect(url_for('home'))
    return redirect(url_for('signin'))

@app.route('/signin', methods=['GET', 'POST'])
def signin():
    if request.method == 'POST':
        name = request.form['name']
        password = request.form['password']
        result = get_db().signin(name, password)
        if result != True:
            return render_template('signin.html', error=result)
        session['username'] = name
        return redirect(url_for('home'))
    else:
        return render_template('signin.html')

@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if request.method == 'POST':
        name = request.form['name']
        password = request.form['password']
        password_repeat = request.form['password-repeat']
        result = get_db().signup(name, password, password_repeat)
        if result != True:
            return render_template('signup.html', error=result)
        session['username'] = name
        return redirect(url_for('home'))
    else:
        return render_template('signup.html')
    
@app.route('/logout', methods=['POST'])
def logout():
    session.pop('username', None)
    session.pop('chat_id', None)
    return redirect(url_for('signin'))

@app.route('/home', methods=['GET'])
def home():
    session.pop('chat_id', None)

    session_username = session.get('username')
    if not session_username:
        return redirect(url_for('signin'))
    db = get_db()
    
    return render_template(
        'home.html',
        self_id=db.get_user_id(session_username),
        self_name=session_username,
        tab_info={
            'tab': 'none',
            'viewing': None,
            'all': None,
            'messages': [],
        }
    )

@app.route('/home/users', methods=['GET'])
def home_users():
    session.pop('chat_id', None)

    session_username = session.get('username')
    if not session_username:
        return redirect(url_for('signin'))
    db = get_db()

    self_id=db.get_user_id(session_username)
    
    return render_template(
        'home.html',
        self_id=db.get_user_id(session_username),
        self_name=db.get_username(self_id),
        tab_info={
            'tab': 'users',
            'viewing': None,
            'all': db.get_all_users(),
            'messages': [],
        },
        online_ids=list(ONLINE_USER_IDS)
    )

@app.route('/home/users/<int:user_id>', methods=['GET'])
def home_user(user_id):
    session.pop('chat_id', None)

    session_username = session.get('username')
    if not session_username:
        return redirect(url_for('signin'))
    db = get_db()
    
    users_list = db.get_all_users()
    users2 = {row[0]: row[1] for row in users_list}

    return render_template(
        'home.html',
        self_id=db.get_user_id(session_username),
        self_name=session_username,
        tab_info={
            'tab': 'users',
            'viewing': user_id,
            'all': db.get_all_users(),
            'messages': db.get_personal_messages(db.get_user_id(session_username), user_id),
        },
        users2=users2,
        username=session_username,
        viewing_username=users2.get(user_id),
        online_ids=list(ONLINE_USER_IDS)
    )

@app.route('/home/chats', methods=['GET'])
def home_chats():
    session.pop('chat_id', None)

    session_username = session.get('username')
    if not session_username:
        return redirect(url_for('signin'))
    db = get_db()

    self_id=db.get_user_id(session_username)
    
    # Отримуємо чати з інформацією про онлайн учасників (не рахуючи себе)
    chats = db.get_all_chats_where_user_is_member(self_id)
    chats_with_status = []
    for chat in chats:
        online_count = db.get_chat_online_members_count(chat[0], ONLINE_USER_IDS, exclude_user_id=self_id)
        chats_with_status.append((chat[0], chat[1], online_count))
    
    return render_template(
        'home.html',
        self_id=self_id,
        self_name=db.get_username(self_id),
        tab_info={
            'tab': 'chats',
            'viewing': None,
            'all': chats_with_status
        },
        owned_chat_ids=db.get_owned_chat_ids(self_id)
    )

@app.route('/home/chats/<int:chat_id>', methods=['GET'])
def home_chat(chat_id):
    session['chat_id'] = chat_id

    session_username = session.get('username')
    if not session_username:
        return redirect(url_for('signin'))
    db = get_db()
    
    return render_template(
        'home.html',
        self_id=db.get_user_id(session_username),
        self_name=session_username,
        tab_info={
            'tab': 'chats',
            'viewing': chat_id,
            'all': db.get_all_chats_where_user_is_member(db.get_user_id(session_username)),
            'messages': db.get_chat_messages(chat_id)
        },
        chat_info={
            'members': db.get_chat_members(chat_id),
            'is_admin': db.is_user_chat_admin(db.get_user_id(session_username), chat_id)
        },
        viewing_username=db.get_chat_name(chat_id),
        owned_chat_ids=db.get_owned_chat_ids(db.get_user_id(session_username))
    )

@app.route('/home/channels', methods=['GET'])
def home_channels():
    session.pop('chat_id', None)

    session_username = session.get('username')
    if not session_username:
        return redirect(url_for('signin'))
    db = get_db()

    self_id=db.get_user_id(session_username)
    
    return render_template(
        'home.html',
        self_id=self_id,
        self_name=db.get_username(self_id),
        tab_info={
            'tab': 'channels',
            'viewing': None,
            'all': db.get_all_channels()
        },
        owned_channel_ids=db.get_owned_channel_ids(self_id)
    )

@app.route('/home/channels/<int:channel_id>', methods=['GET'])
def home_channel(channel_id):
    session.pop('chat_id', None)

    session_username = session.get('username')
    if not session_username:
        return redirect(url_for('signin'))
    db = get_db()
    
    return render_template(
        'home.html',
        self_id=db.get_user_id(session_username),
        self_name=session_username,
        tab_info={
            'tab': 'channels',
            'viewing': channel_id,
            'all': db.get_all_channels(),
            'messages': db.get_channel_messages(channel_id),
            'owner': db.get_channel_owner(channel_id) == session_username
        },
        # Передаём корректный флаг is_admin для канала
        chat_info={
            'is_admin': db.is_user_channel_admin(db.get_user_id(session_username), channel_id)
        },
        viewing_username=db.get_channel_name(channel_id),
        owned_channel_ids=db.get_owned_channel_ids(db.get_user_id(session_username))
    )

@app.route('/delete_chat', methods=['POST'])
def delete_chat():
    session_username = session.get('username')
    if not session_username:
        return redirect(url_for('signin'))
    db = get_db()
    self_id = db.get_user_id(session_username)
    chat_id = request.form.get('chat_id')
    try:
        chat_id_int = int(chat_id)
    except (TypeError, ValueError):
        return redirect(url_for('home_chats'))
    if db.delete_chat(chat_id_int, self_id):
        sio.emit('system', {'message': 'chat_deleted', 'chat_id': chat_id_int}, to=f"chat:{chat_id_int}")
    return redirect(url_for('home_chats'))

@app.route('/delete_msg/<int:id>', methods=['POST'])
def delete_msg(id):
    session_username = session.get('username')
    if not session_username:
        return redirect(url_for('signin'))
    db = get_db()
    user_id = db.get_user_id(session_username)

    scope = request.form.get('scope')
    if not scope:
        if session.get('chat_id'):
            scope = 'chat'
        else:
            scope = 'personal'

    try:
        message_id = int(id)
    except (TypeError, ValueError):
        return redirect(url_for('home'))

    ok = False

    if scope == 'personal':
        room = request.form.get('room')
        other_id = None
        if room:
            try:
                u1, u2 = room.split(':')
                u1 = int(u1); u2 = int(u2)
                other_id = u2 if user_id == u1 else u1
            except Exception:
                other_id = None

        ok = db.delete_personal_message(message_id, user_id)
        if ok and room:
            sio.emit('message_deleted', {'id': message_id, 'scope': 'personal'}, to=room)
        if other_id:
            return redirect(url_for('home_user', user_id=other_id))
        return redirect(url_for('home_users'))

    elif scope == 'chat':
        chat_id = request.form.get('chat_id') or session.get('chat_id')
        try:
            chat_id_int = int(chat_id)
        except (TypeError, ValueError):
            return redirect(url_for('home_chats'))
        ok = db.delete_chat_message(message_id, user_id)
        if ok:
            sio.emit('message_deleted', {'id': message_id, 'scope': 'chat'}, to=f"chat:{chat_id_int}")
        return redirect(url_for('home_chat', chat_id=chat_id_int))

    elif scope == 'channel':
        channel_id = request.form.get('channel_id')

        try:
            channel_id_int = int(channel_id)
        except (TypeError, ValueError):
            return redirect(url_for('home_channels'))
        ok = db.delete_channel_message(message_id, user_id)
        if ok:
            sio.emit('message_deleted', {'id': message_id, 'scope': 'channel'}, to=f"channel:{channel_id_int}")
        return redirect(url_for('home_channel', channel_id=channel_id_int))

    return redirect(url_for('home'))


@app.route('/delete_channel', methods=['POST'])
def delete_channel():
    session_username = session.get('username')
    if not session_username:
        return redirect(url_for('signin'))
    db = get_db()
    self_id = db.get_user_id(session_username)
    channel_id = request.form.get('channel_id')
    try:
        channel_id_int = int(channel_id)
    except (TypeError, ValueError):
        return redirect(url_for('home_channels'))
    if db.delete_channel(channel_id_int, self_id):
        sio.emit('system', {'message': 'channel_deleted', 'channel_id': channel_id_int}, to=f"channel:{channel_id_int}")
    return redirect(url_for('home_channels'))

@app.route('/confirm_delete_chat', methods=['GET', 'POST'])
def confirm_delete_chat():
    return redirect(url_for('home_chats'))

@app.route('/confirm_delete_channel', methods=['GET', 'POST'])
def confirm_delete_channel():
    return redirect(url_for('home_channels'))

@app.route('/create_channel', methods=['GET', 'POST'])
def create_channel():
    session_username = session.get('username')
    if not session_username:
        return redirect(url_for('signin'))
    db = get_db()
    
    if request.method == 'POST':
        name = request.form['name']
        channel_id = db.create_channel(db.get_user_id(session_username), name)
        if not channel_id:
            return render_template('create_channel.html', error='Failed to create channel')
        return redirect(url_for('home_channels'))
    else:
        return render_template('create_channel.html')
    
@app.route('/create_chat', methods=['GET', 'POST'])
def create_chat():
    session_username = session.get('username')
    if not session_username:
        return redirect(url_for('signin'))
    db = get_db()
    
    if request.method == 'POST':
        name = request.form['name']
        creator_id = db.get_user_id(session_username)
        chat_id = db.create_chat(creator_id, name)
        if not chat_id:
            return render_template('create_chat.html', error='Failed to create chat')
        db.add_user_to_chat(chat_id=chat_id, user_id=creator_id)
        return redirect(url_for('home_chats'))
    else:
        return render_template('create_chat.html')
    
@app.route('/add_chat_member', methods=['GET', 'POST'])
def add_chat_member():
    session_username = session.get('username')
    if not session_username:
        return redirect(url_for('signin'))
    db = get_db()
    # Підтримка відкриття сторінки додавання через параметр chat_id
    if request.method == 'GET':
        maybe_chat_id = request.args.get('chat_id')
        if maybe_chat_id:
            try:
                cid = int(maybe_chat_id)
                # Перевіримо, що користувач є учасником цього чату
                if db.is_user_chat_member(cid, db.get_user_id(session_username)):
                    session['chat_id'] = cid
            except (TypeError, ValueError):
                pass

    if request.method == 'POST':
        name = request.form['name']
        user_id = db.get_user_id(name)
        if not user_id:
            # Re-render with context
            chat_id = session.get('chat_id')
            users = db.get_all_users()
            member_ids = {m[0] for m in db.get_chat_members(chat_id)} if chat_id else set()
            return render_template('add_chat_member.html', error='User not found', users=users, member_ids=member_ids)
        added_id = db.add_user_to_chat(chat_id=session.get('chat_id'), user_id=user_id)
        if not added_id:
            chat_id = session.get('chat_id')
            users = db.get_all_users()
            member_ids = {m[0] for m in db.get_chat_members(chat_id)} if chat_id else set()
            return render_template('add_chat_member.html', error='Failed to add member', users=users, member_ids=member_ids)
        return redirect(url_for('home_chat', chat_id=session.get('chat_id')))
    else:
        chat_id = session.get('chat_id')
        users = db.get_all_users()
        member_ids = {m[0] for m in db.get_chat_members(chat_id)} if chat_id else set()
        return render_template('add_chat_member.html', users=users, member_ids=member_ids)

@app.route('/edit_chat', methods=['POST'])
def edit_chat():
    session_username = session.get('username')
    if not session_username:
        return redirect(url_for('signin'))
    db = get_db()
    self_id = db.get_user_id(session_username)
    
    chat_id = request.form.get('chat_id')
    new_name = request.form.get('new_name')
    
    try:
        chat_id_int = int(chat_id)
    except (TypeError, ValueError):
        return redirect(url_for('home_chats'))
    
    if not new_name or len(new_name.strip()) == 0:
        return redirect(url_for('home_chats'))
    
    if db.update_chat_name(chat_id_int, new_name.strip(), self_id):
        sio.emit('system', {'message': 'chat_updated', 'chat_id': chat_id_int, 'new_name': new_name.strip()}, to=f"chat:{chat_id_int}")
    
    return redirect(url_for('home_chats'))

@app.route('/edit_channel', methods=['POST'])
def edit_channel():
    session_username = session.get('username')
    if not session_username:
        return redirect(url_for('signin'))
    db = get_db()
    self_id = db.get_user_id(session_username)

    channel_id = request.form.get('channel_id')
    new_name = request.form.get('new_name')

    try:
        channel_id_int = int(channel_id)
    except (TypeError, ValueError):
        return redirect(url_for('home_channels'))

    if not new_name or len(new_name.strip()) == 0:
        return redirect(url_for('home_channels'))

    # Ожидается, что в db есть метод update_channel_name(channel_id, new_name, user_id)
    if db.update_channel_name(channel_id_int, new_name.strip(), self_id):
        sio.emit('system', {'message': 'channel_updated', 'channel_id': channel_id_int, 'new_name': new_name.strip()}, to=f"channel:{channel_id_int}")

    return redirect(url_for('home_channels'))

if __name__ == '__main__':
    sio.run(app, debug=True, port=2000)