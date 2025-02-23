import hashlib
import os
import sqlite3
import grpc
from concurrent import futures
import time
import queue
import threading
import json
import logging

import chat_pb2
import chat_pb2_grpc
import json

log_path = 'logs/server.log'
db_path = 'data/messenger.db'

# setup logging
logging.basicConfig(level=logging.INFO)
if not os.path.exists('logs'):
    with open(log_path, 'w') as f:
        pass

logging.basicConfig(
    filename=log_path,
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

# import config from config/config.json
if not os.path.exists('config/config.json'):
    print("Error: config.json not found")
    exit(1)
with open('config/config.json') as f:
    config = json.load(f)

try:
    host = config['server_config']['host']
    port = config['server_config']['port']
except KeyError as e:
    print(f"Error: {e} not found in config.json")
    exit(1)

# map of clients to queues for sending responses
clients = {}

class ChatServiceServicer(chat_pb2_grpc.ChatServiceServicer):
    '''
    ChatServiceServicer class for ChatServiceServicer

    This class handles the main chat functionality of the server, sending responses via queues.
    '''
    def Chat(self, request_iterator, context):
        '''
        Chat function for ChatServiceServicer, unique to each client.

        Parameters:
        ----------
        request_iterator : iterator
            iterator of requests from client
        context : context
            All tutorials have this, but it's not used here. Kept for compatibility.
        '''
        username = None
        # queue for sending responses to client
        client_queue = queue.Queue()

        # handle incoming requests
        def handle_requests():
            nonlocal username
            try:
                for req in request_iterator:
                    if req.action == chat_pb2.CHECK_USERNAME:
                        # check if username is already in use
                        sqlcon = sqlite3.connect(db_path)
                        sqlcur = sqlcon.cursor()

                        sqlcur.execute("SELECT * FROM users WHERE username=?", (req.username,))

                        # if username is already in use, send response with success=False
                        # otherwise, send response with success=True
                        if sqlcur.fetchone():
                            client_queue.put(chat_pb2.ChatResponse(action=chat_pb2.CHECK_USERNAME, result=False))
                        else:
                            client_queue.put(chat_pb2.ChatResponse(action=chat_pb2.CHECK_USERNAME, result=True))
                        sqlcon.close()

                    elif req.action == chat_pb2.LOGIN:
                        sqlcon = sqlite3.connect(db_path)
                        sqlcur = sqlcon.cursor()

                        sqlcur.execute("SELECT * FROM users WHERE username=? AND password=?", (req.username, req.password))

                        # if username and password match, send response with success=True
                        # otherwise, send response with success=False
                        if sqlcur.fetchone():
                            client_queue.put(chat_pb2.ChatResponse(action=chat_pb2.LOGIN, result=True))
                        else:
                            client_queue.put(chat_pb2.ChatResponse(action=chat_pb2.LOGIN, result=False))
                        sqlcon.close()

                    elif req.action == chat_pb2.REGISTER:
                        sqlcon = sqlite3.connect(db_path)
                        sqlcur = sqlcon.cursor()

                        # check to make sure username is not already in use
                        sqlcur.execute("SELECT * FROM users WHERE username=?", (req.username,))
                        if sqlcur.fetchone():
                            client_queue.put(chat_pb2.ChatResponse(action=chat_pb2.REGISTER, result=False))
                        else:
                            # add new user to database
                            sqlcur.execute("INSERT INTO users (username, password) VALUES (?, ?)", (req.username, req.password))
                            sqlcon.commit()
                            client_queue.put(chat_pb2.ChatResponse(action=chat_pb2.REGISTER, result=True))

                        sqlcon.close()

                        # add user to clients
                        username = req.username
                        clients[username] = client_queue

                        # send ping_user to all clients
                        for user_q in clients.values():
                            user_q.put(chat_pb2.ChatResponse(action=chat_pb2.PING_USER, username=username))

                        # ping all online users
                    elif req.action == chat_pb2.LOAD_CHAT:
                        sqlcon = sqlite3.connect(db_path)
                        sqlcur = sqlcon.cursor()

                        username = req.username
                        user2 = req.user2
                        try:
                            sqlcur.execute(
                                "SELECT sender, recipient, message, message_id FROM messages WHERE (sender=? AND recipient=?) OR (sender=? AND recipient=?) ORDER BY time",
                                (username, user2, user2, username),
                            )
                            result = sqlcur.fetchall()
                        except Exception as e:
                            logging.error(f"Error in Load Chat: {e}")
                            result = []
                        
                        client_queue.put(chat_pb2.ChatResponse(action=chat_pb2.LOAD_CHAT, messages=result))

                    elif req.action == chat_pb2.SEND_MESSAGE:
                        sender = req.sender
                        recipient = req.recipient
                        message = req.message
                        sqlcon = sqlite3.connect(db_path)
                        sqlcur = sqlcon.cursor()

                        try:
                            sqlcur.execute(
                                "INSERT INTO messages (sender, recipient, message) VALUES (?, ?, ?)",
                                (sender, recipient, message),
                            )
                            sqlcon.commit()

                            # get the message_id
                            sqlcur.execute(
                                "SELECT message_id FROM messages WHERE sender=? AND recipient=? AND message=? ORDER BY time DESC LIMIT 1",
                                (sender, recipient, message),
                            )
                            message_id = sqlcur.fetchone()[0]

                            # send message to recipient
                            client_queue.put(chat_pb2.ChatResponse(action=chat_pb2.SEND_MESSAGE, message_id=message_id))

                            # ping recipient if online
                            if recipient in clients:
                                clients[recipient].put(chat_pb2.ChatResponse(action=chat_pb2.PING, sender=sender, sent_message=message, message_id=message_id))

                        except:
                            logging.error("Error sending message")
                            message_id = None

                        sqlcon.close()
                    elif req.action == chat_pb2.PING:
                        action = req.action
                        sender = req.sender
                        sent_message = req.sent_message
                        message_id = req.message_id

                        client_queue.put(chat_pb2.ChatResponse(action=action, sender=sender, sent_message=sent_message, message_id=message_id))

                        sqlcon = sqlite3.connect(db_path)
                        sqlcur = sqlcon.cursor()

                        logging.info(f"Updating message {message_id} to delivered.")

                        sqlcur.execute(
                            "UPDATE messages SET delivered=1 WHERE message_id=?", (message_id,)
                        )
                        sqlcon.commit()

                        sqlcon.close()
                    elif req.action == chat_pb2.VIEW_UNDELIVERED:
                        sqlcon = sqlite3.connect(db_path)
                        sqlcur = sqlcon.cursor()

                        username = req.username
                        n_messages = req.n_messages

                        sqlcur.execute(
                            "SELECT sender, recipient, message, message_id FROM messages WHERE recipient=? AND delivered=0 ORDER BY time DESC LIMIT ?",
                            (username, n_messages),
                        )
                        result = sqlcur.fetchall()
                        queue.put(chat_pb2.ChatResponse(action=chat_pb2.VIEW_UNDELIVERED, messages=result))

                        sqlcur.execute(
                            "UPDATE messages SET delivered=1 WHERE recipient=?", (username,)
                        )

                        sqlcon.commit()
                        sqlcon.close()
                    elif req.action == chat_pb2.DELETE_MESSAGE:
                        sqlcon = sqlite3.connect(db_path)
                        sqlcur = sqlcon.cursor()

                        message_id = req.message_id
                        sqlcur.execute("DELETE FROM messages WHERE message_id=?", (message_id,))
                        sqlcon.commit()

                        sqlcon.close()
                        queue.put(chat_pb2.ChatResponse(action=chat_pb2.DELETE_MESSAGE, message_id=message_id))
                    elif req.action == chat_pb2.DELETE_ACCOUNT:
                        sqlcon = sqlite3.connect(db_path)
                        sqlcur = sqlcon.cursor()

                        username = req.username
                        passhash = req.password


                        passhash = hashlib.sha256(passhash.encode()).hexdigest()
                        sqlcur.execute("SELECT passhash FROM users WHERE username=?", (username,))

                        result = sqlcur.fetchone()
                        if result:
                            # username exists and passhash matches
                            if result[0] == passhash:
                                sqlcur.execute("DELETE FROM users WHERE username=?", (username,))
                                sqlcur.execute("DELETE FROM messages WHERE sender=? OR recipient=?", (username, username))
                                sqlcon.commit()

                                client_queue.put(chat_pb2.ChatResponse(action=chat_pb2.DELETE_ACCOUNT, result=True))
                                # tell server to ping users to update their chat, remove from connected users
                            # username exists but passhash is wrong
                            else:
                                client_queue.put(chat_pb2.ChatResponse(action=chat_pb2.DELETE_ACCOUNT, result=False))
                        else:
                            # username doesn't exist
                            client_queue.put(chat_pb2.ChatResponse(action=chat_pb2.DELETE_ACCOUNT, result=False))

                        sqlcon.close()
                    elif req.action == chat_pb2.PING_USER:
                        # ping that a user has been added or deleted
                        action = req.action
                        ping_user = req.ping_user
                        client_queue.put(chat_pb2.ChatResponse(action=action, ping_user=ping_user))
                    else:
                        logging.error(f"Invalid action: {req.action}")
            except Exception as e:
                print("Error handling requests:", e)
            finally:
                if username in clients:
                    del clients[username]
                    print(f"{username} disconnected.")

        # Run request handling in a separate thread.
        threading.Thread(target=handle_requests, daemon=True).start()

        # Continuously yield responses from the client's queue.
        while True:
            try:
                response = client_queue.get()
                yield response
            except Exception as e:
                break


def serve():
    '''
    Main loop for server. Runs server on separate thread.
    '''
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    chat_pb2_grpc.add_ChatServiceServicer_to_server(ChatServiceServicer(), server)
    server.add_insecure_port(f"{host}:{port}")
    server.start()
    print(f"Server started on {host}:{port}")
    try:
        while True:
            time.sleep(86400)
    except KeyboardInterrupt:
        server.stop(0)

if __name__ == '__main__':
    serve()
