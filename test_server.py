import sqlite3
import chat_pb2
import hashlib

db_path = "data/test_database.db"

def handle_requests(req, username=None):
    # print size of req in bytes

    if req.action == chat_pb2.CHECK_USERNAME:
        # check if username is already in use
        sqlcon = sqlite3.connect(db_path)
        sqlcur = sqlcon.cursor()

        sqlcur.execute(
            "SELECT * FROM users WHERE username=?", (req.username,)
        )

        # if username is already in use, send response with result=False
        # otherwise, send response with result=True
        if sqlcur.fetchone():
            sqlcon.close()
            return chat_pb2.ChatResponse(action=chat_pb2.CHECK_USERNAME, result=False)
        else:
            sqlcon.close()
            return chat_pb2.ChatResponse(action=chat_pb2.CHECK_USERNAME, result=True)

    elif req.action == chat_pb2.LOGIN:
        sqlcon = sqlite3.connect(db_path)
        sqlcur = sqlcon.cursor()

        req.passhash = hashlib.sha256(req.passhash.encode()).hexdigest()

        sqlcur.execute(
            "SELECT * FROM users WHERE username=? AND passhash=?",
            (req.username, req.passhash),
        )

        # if username and password match, send response with result=True
        # otherwise, send response with result=False
        if sqlcur.fetchone():
            sqlcur.execute(
                "SELECT COUNT(*) FROM messages WHERE recipient=? AND delivered=0",
                (req.username,),
            )

            n_undelivered = sqlcur.fetchone()[0]

            response = chat_pb2.ChatResponse(
                action=chat_pb2.LOGIN,
                result=True,
                users=[
                    s[0]
                    for s in sqlcur.execute(
                        "SELECT username FROM users WHERE username != ?",
                        (req.username,),
                    ).fetchall()
                ],
                n_undelivered=n_undelivered,
            )
            sqlcon.close()

            return response
        else:
            sqlcon.close()
            return chat_pb2.ChatResponse(action=chat_pb2.LOGIN, result=False)

    elif req.action == chat_pb2.REGISTER:
        sqlcon = sqlite3.connect(db_path)
        sqlcur = sqlcon.cursor()

        # check to make sure username is not already in use
        sqlcur.execute(
            "SELECT * FROM users WHERE username=?", (req.username,)
        )
        if sqlcur.fetchone():
            sqlcon.close()
            return chat_pb2.ChatResponse(action=chat_pb2.REGISTER, result=False)
        else:
            # add new user to database
            req.passhash = hashlib.sha256(req.passhash.encode()).hexdigest()
            sqlcur.execute(
                "INSERT INTO users (username, passhash) VALUES (?, ?)",
                (req.username, req.passhash),
            )
            sqlcon.commit()
            response = chat_pb2.ChatResponse(
                action=chat_pb2.REGISTER,
                result=True,
                users=[
                    s[0]
                    for s in sqlcur.execute(
                        "SELECT username FROM users WHERE username != ?",
                        (req.username,),
                    ).fetchall()
                ],
            )
            sqlcon.close()

            return response

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
            result = []

        formatted_messages = []
        for sender, recipient, message, message_id in result:
            formatted_messages.append(
                chat_pb2.ChatMessage(
                    sender=sender,
                    recipient=recipient,
                    message=message,
                    message_id=message_id,
                )
            )
        sqlcon.close()
        return chat_pb2.ChatResponse(action=chat_pb2.LOAD_CHAT, messages=formatted_messages)

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

            response = chat_pb2.ChatResponse(
                action=chat_pb2.SEND_MESSAGE, message_id=message_id
            )

            sqlcon.close()
            return response

        except Exception as e:
            sqlcon.close()
            return None

    elif req.action == chat_pb2.PING:
        action = req.action
        sender = req.sender
        sent_message = req.sent_message
        message_id = req.message_id

        response = chat_pb2.ChatResponse(
            action=action,
            sender=sender,
            sent_message=sent_message,
            message_id=message_id,
        )

        # update the message status to delivered in the database
        sqlcon = sqlite3.connect(db_path)
        sqlcur = sqlcon.cursor()
        sqlcur.execute(
            "UPDATE messages SET delivered=1 WHERE message_id=?",
            (message_id,),
        )
        sqlcon.commit()
        sqlcon.close()

        return response

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

        messages_formatted = []
        for sender, recipient, message, message_id in result:
            messages_formatted.append(
                chat_pb2.ChatMessage(
                    sender=sender,
                    recipient=recipient,
                    message=message,
                    message_id=message_id,
                )
            )

        sqlcur.execute(
            "UPDATE messages SET delivered=1 WHERE recipient=?",
            (username,),
        )
        sqlcon.commit()
        sqlcon.close()
        return chat_pb2.ChatResponse(action=chat_pb2.VIEW_UNDELIVERED, messages=messages_formatted)

    elif req.action == chat_pb2.DELETE_MESSAGE:
        sqlcon = sqlite3.connect(db_path)
        sqlcur = sqlcon.cursor()

        message_id = req.message_id
        sqlcur.execute(
            "DELETE FROM messages WHERE message_id=?", (message_id,)
        )
        sqlcon.commit()
        sqlcon.close()

        response = chat_pb2.ChatResponse(action=chat_pb2.DELETE_MESSAGE, message_id=message_id)


        return response

    elif req.action == chat_pb2.DELETE_ACCOUNT:
        sqlcon = sqlite3.connect(db_path)
        sqlcur = sqlcon.cursor()

        username = req.username
        passhash = req.passhash

        passhash = hashlib.sha256(passhash.encode()).hexdigest()
        sqlcur.execute(
            "SELECT passhash FROM users WHERE username=?", (username,)
        )

        result = sqlcur.fetchone()
        if result:
            # username exists and passhash matches
            if result[0] == passhash:
                sqlcur.execute(
                    "DELETE FROM users WHERE username=?", (username,)
                )
                sqlcur.execute(
                    "DELETE FROM messages WHERE sender=? OR recipient=?",
                    (username, username),
                )
                sqlcon.commit()

                response = chat_pb2.ChatResponse(action=chat_pb2.DELETE_ACCOUNT, result=True)


                sqlcon.close()
                return response
            else:
                sqlcon.close()
                return chat_pb2.ChatResponse(action=chat_pb2.DELETE_ACCOUNT, result=False)
        else:
            sqlcon.close()
            return chat_pb2.ChatResponse(action=chat_pb2.DELETE_ACCOUNT, result=False)

    elif req.action == chat_pb2.PING_USER:
        action = req.action
        ping_user = req.ping_user
        return chat_pb2.ChatResponse(action=action, ping_user=ping_user)

    else:
        return None