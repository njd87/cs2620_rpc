from concurrent import futures
import unittest
import os
import sqlite3

import grpc
import chat_pb2
import chat_pb2_grpc
from server import ChatServiceServicer
from setup import reset_database, structure_tables
from test_server import handle_requests

unittest.TestLoader.sortTestMethodsUsing = None

class TestDatabaseSetup(unittest.TestCase):
    '''
    Tests "setup.py" file for resetting and structuring the database.

    Tests the following functions:
    - reset_database
    - structure_tables
    '''
    def test_reset_database(self):
        # check if the database file is deleted
        reset_database("data/test_database.db")
        self.assertFalse(os.path.exists("data/test_database.db"))

    def test_structure_tables(self):
        # check if the tables are created correctly
        structure_tables("data/test_database.db")
        conn = sqlite3.connect("data/test_database.db")
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='users';")
        self.assertIsNotNone(cursor.fetchone())
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='messages';")
        self.assertIsNotNone(cursor.fetchone())
        conn.commit()
        conn.close()

class TestServerProcessResponse(unittest.TestCase):
    '''
    Test cases for communicating between the server and client via JSON encoding and decoding.
    '''
    
    @classmethod
    def setUpClass(cls):
        # Code to run once at the beginning of the test class
        # check to see if data/test_database.db exists
        # if it does, delete it
        if os.path.exists("data/test_database.db"):
            os.remove("data/test_database.db")
            print("Deleted existing test_database.db")

        structure_tables("data/test_database.db")

    def test1b_register_user(self):
        # register user, check if it exists in the database
        request = chat_pb2.ChatRequest(action=chat_pb2.REGISTER, username="foo", passhash="bar")

        response = handle_requests(request)

        self.assertEqual(response.result, True)
        self.assertEqual(response.users, [])

        conn = sqlite3.connect("data/test_database.db")
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM users WHERE username='foo';")
        user = cursor.fetchone()
        self.assertIsNotNone(user)
        self.assertEqual(user[1], 'foo')
        cursor.execute("SELECT COUNT(*) FROM users;")
        count = cursor.fetchone()[0]

        # should be in database now
        self.assertEqual(count, 1)
        conn.close()

    def test1c_register_user_exists(self):
        # if user already exists, it should return False
        request = chat_pb2.ChatRequest(action=chat_pb2.REGISTER, username="foo", passhash="bar")

        response = handle_requests(request)

        self.assertEqual(response.result, False)

        # double check if user is in database
        conn = sqlite3.connect("data/test_database.db")
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM users WHERE username='foo';")
        user = cursor.fetchone()
        self.assertIsNotNone(user)
        self.assertEqual(user[1], 'foo')
        cursor.execute("SELECT COUNT(*) FROM users;")
        count = cursor.fetchone()[0]
        self.assertEqual(count, 1)
        conn.close()

    def test1d_login_user(self):
        # login existing user, check return true
        request = chat_pb2.ChatRequest(action=chat_pb2.LOGIN, username="foo", passhash="bar")

        response = handle_requests(request)

        self.assertEqual(response.result, True)

    def test1e_login_user_invalid(self):
        # login with invalid password, should return False
        request = chat_pb2.ChatRequest(action=chat_pb2.LOGIN, username="foo", passhash="baz")

        response = handle_requests(request)

        self.assertEqual(response.result, False)

    def test1f_register_other(self):
        # register another user, check if it exists in the database
        request = chat_pb2.ChatRequest(action=chat_pb2.REGISTER, username="bar", passhash="baz")
        response = handle_requests(request)

        self.assertEqual(response.result, True)
        self.assertEqual(response.users, ["foo"])
    
    def test2a_send_message(self):
        # send message between two users, check if it exists in the database
        request = chat_pb2.ChatRequest(action=chat_pb2.SEND_MESSAGE, sender="foo", recipient="bar", message="Hello, World!")
        response = handle_requests(request)

        self.assertIsNotNone(response.message_id)

        conn = sqlite3.connect("data/test_database.db")
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM messages WHERE message_id=?;", (response.message_id,))
        message = cursor.fetchone()
        self.assertIsNotNone(message)
        self.assertEqual(message[1], 'foo')
        self.assertEqual(message[2], 'bar')
        self.assertEqual(message[3], 'Hello, World!')
        conn.close()

    def test2b_send_many_msgs(self):
        # send many messages between two users, check if they exist in the database
        for i in range(1000):
            request = chat_pb2.ChatRequest(action=chat_pb2.SEND_MESSAGE, sender="foo", recipient="bar", message=f"Message {i}")
            response = handle_requests(request)

            self.assertIsNotNone(response.message_id)

        conn = sqlite3.connect("data/test_database.db")
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM messages WHERE sender='foo' AND recipient='bar';")
        count = cursor.fetchone()[0]
        self.assertEqual(count, 1001)
        conn.close()

    def test3a_ping(self):
        # ping user, check if message is delivered
        request = chat_pb2.ChatRequest(action=chat_pb2.PING, sender="foo", sent_message="Hello, World!", message_id=1)
        response = handle_requests(request)

        conn = sqlite3.connect("data/test_database.db")
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM messages WHERE sender='foo' AND delivered=1;")
        count = cursor.fetchone()[0]
        self.assertEqual(count, 1)
        conn.close()

    def test3b_load_chat(self):
        # load chat between two users, check if messages are returned
        request = chat_pb2.ChatRequest(action=chat_pb2.LOAD_CHAT, username="foo", user2="bar")
        response = handle_requests(request)


        # check to make sure response.messages is not empty
        self.assertNotEqual(response.messages, [])

    def test3c_load_chat_empty(self):
        # check to make sure empty chat returns no messages
        request = chat_pb2.ChatRequest(action=chat_pb2.LOAD_CHAT, username="foo", user2="baz")
        response = handle_requests(request)
        
        self.assertEqual(response.messages, [])

    def test4a_view_undelivered(self):
        # view undelivered messages, check if they are returned
        request = chat_pb2.ChatRequest(action=chat_pb2.VIEW_UNDELIVERED, username="bar", n_messages=10)
        _ = handle_requests(request)

        # check if undelieverd are marked as delivered
        conn = sqlite3.connect("data/test_database.db")
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM messages WHERE recipient='bar' AND delivered=0;")
        count = cursor.fetchone()[0]
        self.assertEqual(count, 0)
        conn.close()

    def test5a_delete_message(self):
        # delete message, check if it is removed from the database
        request = chat_pb2.ChatRequest(action=chat_pb2.DELETE_MESSAGE, message_id=1)
        _ = handle_requests(request)

        conn = sqlite3.connect("data/test_database.db")
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM messages WHERE message_id=1;")
        count = cursor.fetchone()[0]
        self.assertEqual(count, 0)
        conn.close()

    def test5b_delete_account_invalid_pass(self):
        # delete account with invalid password, should return False
        request = chat_pb2.ChatRequest(action=chat_pb2.DELETE_ACCOUNT, username="foo", passhash="baz")
        response = handle_requests(request)

        self.assertEqual(response.result, False)

        conn = sqlite3.connect("data/test_database.db")
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM users WHERE username='foo';")
        count = cursor.fetchone()[0]
        self.assertEqual(count, 1)

        cursor.execute("SELECT COUNT(*) FROM messages WHERE sender='foo' OR recipient='foo';")
        count = cursor.fetchone()[0]
        self.assertNotEqual(count, 0)
        conn.close()

    def test5c_delete_account_invalid_user(self):
        # delete account with invalid username, should return False
        request = chat_pb2.ChatRequest(action=chat_pb2.DELETE_ACCOUNT, username="baz", passhash="bar")
        response = handle_requests(request)

        self.assertEqual(response.result, False)

        conn = sqlite3.connect("data/test_database.db")
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM users WHERE username='baz';")
        count = cursor.fetchone()[0]
        self.assertEqual(count, 0)
        conn.close()

    def test5d_delete_account(self):
        # delete account, check if it is removed from the database
        request = chat_pb2.ChatRequest(action=chat_pb2.DELETE_ACCOUNT, username="foo", passhash="bar")
        response = handle_requests(request)

        self.assertEqual(response.result, True)

        conn = sqlite3.connect("data/test_database.db")
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM users WHERE username='foo';")
        count = cursor.fetchone()[0]
        self.assertEqual(count, 0)

        cursor.execute("SELECT COUNT(*) FROM messages WHERE sender='foo' OR recipient='foo';")
        count = cursor.fetchone()[0]
        self.assertEqual(count, 0)
        conn.close()


if __name__ == "__main__":
    unittest.main()
    # delete data/test_database.db
    if os.path.exists("data/test_database.db"):
        os.remove("data/test_database.db")
        print("Deleted test_database.db")

'''
Manual UI unit tests:

- Correctly register a user
- Correctly login a user
- Correctly fails login with incorrect password
- Correctly fails register with existing user
- Correctly fails to submit empty message/usernames
- Correctly reads undelivered messages
- Correctly selects number of undelivered messages
- Correctly sends messages live
- Correctly sends pings
- Correctly deletes own messages
- Correctly fails to delete other users' messages
- Correctly deletes own account
- Correctly fails to delete other users' accounts
- Correctly pings users' "users" tab when user deletes
- Correctly pings users' "users" tab when user registers
- Correctly loads chat history for existing chat
- Correctly loads chat history for non-existing chat
- Correctly fails to delete account with incorrect password

'''