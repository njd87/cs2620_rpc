import os
import queue
import sys
import threading
import tkinter as tk
import json
import logging

import grpc

import chat_pb2
import chat_pb2_grpc

# log to a file
log_file = "logs/client.log"
db_file = "data/messenger.db"

logging.basicConfig(
    filename=log_file,
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

# if the file does not exist in the current directory, create it
if not os.path.exists(log_file):
    with open(log_file, "w") as f:
        pass

# A thread-safe queue for outgoing ChatRequests.
outgoing_queue = queue.Queue()


def request_generator():
    """Yield ChatRequests from the outgoing_queue."""
    while True:
        req = outgoing_queue.get()
        yield req


class ClientUI:
    """
    The client UI for the messenger.

    The client UI is a tkinter application that has a few different states:
    - User Entry
    - Login
    - Register
    - Main
    - Delete

    The user entry is the first screen that asks for a username.
    The login screen asks for a username and password.
    The register screen asks for a username and password.

    The main screen has a list of users, a chat window, and a chat entry.

    The delete screen asks for a username and password to confirm deletion.

    The client UI is responsible for sending requests to the server and processing responses.
    """

    def __init__(self):
        """
        Initialize the client UI.
        """
        self.root = tk.Tk()
        self.root.title("Messenger")
        self.root.geometry("800x600")

        self.channel = grpc.insecure_channel(f"{host}:{port}")
        self.stub = chat_pb2_grpc.ChatServiceStub(self.channel)

        self.credentials = None

        # start connection
        # Start a background thread to process server responses.
        threading.Thread(target=self.handle_responses, daemon=True).start()

        # setup first screen
        self.setup_user_entry()

        # these are variables that are used to store data from the server

        # online users
        self.users = []

        # current messages in conversation
        self.loaded_messages = []

        # incoming pings
        self.incoming_pings = []

        # undelivered messages
        self.undelivered_messages = []
        self.n_undelivered = 0

        # user that is currently being messaged
        self.connected_to = None

        # run the tkinter main loop
        self.root.mainloop()

    def handle_responses(self):
        """
        Constantly check for responses from the server and process them.
        """
        try:
            responses = self.stub.Chat(request_generator())
            for resp in responses:
                logging.info(f'Size of response: {sys.getsizeof(resp)}')
                action = resp.action
                if action == chat_pb2.CHECK_USERNAME:
                    # destroy current screen
                    self.destroy_user_entry()
                    # if the username exists, go to login
                    # if not, go to register
                    if not resp.result:
                        self.setup_login()
                    else:
                        self.setup_register()
                elif action == chat_pb2.LOGIN:
                    # if login successful, update users and go to undelivered
                    # if not, go to login with failed
                    if resp.result:
                        self.users = list(resp.users)
                        self.n_undelivered = resp.n_undelivered
                        self.credentials = self.login_entry.get()
                        self.login_frame.destroy()
                        self.setup_undelivered()
                    else:
                        self.login_frame.destroy()
                        self.setup_login(failed=True)
                elif action == chat_pb2.REGISTER:
                    # if successful login, update users and go to main
                    # if not, go to register with failed
                    if resp.result:
                        self.users = list(resp.users)
                        self.credentials = self.register_entry.get()
                        self.register_frame.destroy()
                        self.setup_main()
                    else:
                        self.register_username_exists_label.pack()
                elif action == chat_pb2.LOAD_CHAT:
                    # load the chat for the connected user
                    # format messages correctly
                    messages = []

                    for cm in resp.messages:
                        messages.append(
                            (cm.sender, cm.recipient, cm.message, cm.message_id)
                        )

                    self.loaded_messages = messages
                    self.rerender_messages()
                elif action == chat_pb2.SEND_MESSAGE:
                    # a message was sent currently to the user
                    self.loaded_messages.append(
                        (
                            self.credentials,
                            self.connected_to,
                            self.chat_entry.get(),
                            resp.message_id,
                        )
                    )
                    self.chat_entry.delete(0, tk.END)
                    self.rerender_messages()
                elif action == chat_pb2.VIEW_UNDELIVERED:
                    # format undelivered messages correctly
                    messages = []

                    for cm in resp.messages:
                        messages.append(
                            (cm.sender, cm.recipient, cm.message, cm.message_id)
                        )

                    self.undelivered_messages = messages
                    self.rerender_undelivered()
                elif action == chat_pb2.PING:
                    if self.connected_to == resp.sender:
                        # if the message_id already exists in current loaded messages, remove it
                        if resp.message_id in [m[3] for m in self.loaded_messages]:
                            self.loaded_messages = [
                                m
                                for m in self.loaded_messages
                                if m[3] != resp.message_id
                            ]
                        else:
                            self.loaded_messages.append(
                                (
                                    self.connected_to,
                                    self.credentials,
                                    resp.sent_message,
                                    resp.message_id,
                                )
                            )
                        self.rerender_messages()
                    else:
                        self.incoming_pings.append((resp.sender, resp.sent_message))
                        self.rerender_pings()
                elif action == chat_pb2.DELETE_MESSAGE:
                    # find message in loaded messages and delete it
                    index = self.chat_text.curselection()[0] - 1
                    del self.loaded_messages[index]
                    self.chat_entry.delete(0, tk.END)
                    self.rerender_messages()
                elif action == chat_pb2.DELETE_ACCOUNT:
                    # if successful, reset login vars and go to deleted
                    # if not, go to settings with failed
                    if resp.result:
                        self.reset_login_vars()
                        self.destroy_settings()
                        self.setup_deleted()
                    else:
                        self.destroy_settings()
                        self.setup_settings(failed=True)
                elif action == chat_pb2.PING_USER:
                    # if the user is connected, remove them from the users list
                    # if the user is the connected user, reset the chat
                    # if the user is the connected user, remove the pings

                    # if it is a new user, add them to the users list
                    pinging_user = resp.ping_user
                    if pinging_user in self.users:
                        self.users = [
                            user for user in self.users if user != pinging_user
                        ]
                        self.rerender_users()
                        if self.connected_to == pinging_user:
                            self.connected_to = None
                            self.loaded_messages = []
                            self.rerender_messages()
                        self.incoming_pings = [
                            ping
                            for ping in self.incoming_pings
                            if ping[0] != pinging_user
                        ]
                        self.rerender_pings()
                    elif pinging_user != self.credentials:
                        self.users.append(pinging_user)
                        self.rerender_users()
        except grpc.RpcError as e:
            logging.error(f"Error receiving response: {e}")

    def reset_login_vars(self):
        """
        Reset the login variables.
        """
        self.credentials = None
        self.users = []
        self.loaded_messages = []
        self.incoming_pings = []
        self.undelivered_messages = []
        self.n_undelivered = 0
        self.connected_to = None

    """
    Functions starting with "send_" are used to send requests to the server.

    These are used when the user interacts with the tkinter window.
    """

    def send_logreg_request(self, action, username, password, confirm_password=None):
        """
        Send a login or register request to the server, depending on the action.

        Parameters
        ----------
        action : str
            The action to take. Either "login" or "register".
        username : str
            The username to send.
        password : str
            The password to send.
        confirm_password : str
            The confirm password to send. Only used for registration.
        """
        # create a request
        request = chat_pb2.ChatRequest(
            action=action,
            username=username,
            passhash=password,
        )

        outgoing_queue.put(request)

    def send_user_check_request(self, username):
        """
        Send a request to check if the username exists.

        Parameters
        ----------
        username : str
            The username to check.
        """
        # create a request

        request = chat_pb2.ChatRequest(
            action=chat_pb2.CHECK_USERNAME,
            username=username,
        )

        outgoing_queue.put(request)

    def send_chat_load_request(self, username):
        """
        Send a request to load the chat for the selected user.
        To be done whenever a user wants to start messaging someone.

        Parameters
        ----------
        username : str
            The username to load the chat for.
        """
        # create a request

        request = chat_pb2.ChatRequest(
            action=chat_pb2.LOAD_CHAT,
            username=self.credentials,
            user2=username,
        )

        outgoing_queue.put(request)

        self.connected_to = username
        self.incoming_pings = [
            ping for ping in self.incoming_pings if ping[0] != username
        ]  # KG: could cause slowdown
        self.rerender_pings()

    def send_message_request(self, message):
        """
        Send a request to send a message to the connected user.

        Parameters
        ----------
        message : str
            The message to send.
        """
        if not self.connected_to:
            return
        # create a request

        request = chat_pb2.ChatRequest(
            action=chat_pb2.SEND_MESSAGE,
            sender=self.credentials,
            recipient=self.connected_to,
            message=message,
        )

        outgoing_queue.put(request)

        # self.check_send_message_request()

    def send_undelivered_request(self, n_messages):
        """
        Send a request to view undelivered messages.

        Parameters
        ----------
        n_messages : int
            The number of messages to view.
        """

        # cast n_messages as int
        try:
            n_messages = int(n_messages)
        except ValueError:
            self.out_of_range_warning_label.pack()
            return

        if n_messages < 0 or n_messages > self.n_undelivered:
            self.out_of_range_warning_label.pack()
            return

        # create a request
        request = chat_pb2.ChatRequest(
            action=chat_pb2.VIEW_UNDELIVERED,
            username=self.credentials,
            n_messages=n_messages,
        )

        outgoing_queue.put(request)

        # get rid of out of range warning
        self.out_of_range_warning_label.destroy()

    def send_delete_message_request(self, message_inx):
        """
        Delete a message from the chat.
        """
        logging.info(
            f"Deleting Message: {self.loaded_messages[message_inx]} from {self.credentials} to {self.connected_to}"
        )
        # check if the message is from the user
        if self.loaded_messages[message_inx][0] == self.credentials:
            message_id = self.loaded_messages[message_inx][3]

            request = chat_pb2.ChatRequest(
                action=chat_pb2.DELETE_MESSAGE,
                message_id=message_id,
                sender=self.credentials,
                recipient=self.connected_to,
            )

            outgoing_queue.put(request)

        else:
            logging.info(f"Cannot delete message. Message not from {self.credentials}")

    def send_delete_request(self, password):
        """
        Send a request to delete the account.
        """
        logging.info(f"Deleting Account: {self.credentials}")

        request = chat_pb2.ChatRequest(
            action=chat_pb2.DELETE_ACCOUNT,
            username=self.credentials,
            passhash=password,
        )

        outgoing_queue.put(request)

    """
    Functions starting with "setup_" are used to set up the state of the tkinter window.

    Each setup function has a corresponding "destroy_" function to remove the widgets from the window.
    """

    def setup_user_entry(self):
        """
        Set up the user entry screen.

        Has:
        - A label that says "Enter username:"
        - An entry for the user to enter their username.
        - A button that says "Enter" to submit the username.
        """
        self.user_entry_frame = tk.Frame(self.root)
        self.user_entry_frame.pack()
        self.user_entry_label = tk.Label(self.user_entry_frame, text="Enter username:")
        self.user_entry_label.pack()
        self.user_entry = tk.Entry(self.user_entry_frame)
        self.user_entry.pack()
        self.user_entry_button = tk.Button(
            self.user_entry_frame,
            text="Enter",
            command=lambda: (
                self.send_user_check_request(self.user_entry.get())
                if self.user_entry.get()
                else None
            ),
        )

        self.user_entry_button.pack()

    def destroy_user_entry(self):
        """
        Destroy the user entry screen.
        """
        self.user_entry_frame.destroy()

    def setup_login(self, failed=False):
        """
        Set up the login screen.

        Has:
        - A label that says "Enter your username:"
        - An entry for the user to enter their username.
        - A label that says "Enter your password:"
        - An entry for the user to enter their password.
        - A button that says "Login" to submit the login.
        - A label that says "Login failed, username/password incorrect" that is hidden by default.
        """
        self.login_frame = tk.Frame(self.root)
        self.login_frame.pack()
        self.login_label = tk.Label(self.login_frame, text="Enter your username:")
        self.login_label.pack()
        self.login_entry = tk.Entry(self.login_frame)
        self.login_entry.pack()
        self.login_password_label = tk.Label(
            self.login_frame, text="Enter your password:"
        )
        self.login_password_label.pack()
        self.login_password_entry = tk.Entry(self.login_frame)
        self.login_password_entry.pack()
        self.login_button = tk.Button(
            self.login_frame,
            text="Login",
            command=lambda: (
                self.send_logreg_request(  # KG: design choice for empty strings?
                    chat_pb2.LOGIN,
                    self.login_entry.get(),
                    self.login_password_entry.get(),
                )
                if self.login_entry.get() and self.login_password_entry.get()
                else None
            ),
        )
        self.login_button.pack()

        self.back_button_login = tk.Button(
            self.login_frame,
            text="Back",
            command=lambda: [self.destroy_login(), self.setup_user_entry()],
        )
        self.back_button_login.pack()

        self.login_failed_label = tk.Label(
            self.login_frame, text="Login failed, username/password incorrect"
        )

        if failed:
            self.login_failed_label.pack()

    def destroy_login(self):
        """
        Destroy the login screen.
        """
        self.login_frame.destroy()

    def setup_undelivered(self):
        """
        Set up the undelivered screen.

        Has:
        - A label that says "Undelivered messages"
        - A listbox that has all the undelivered messages.
        - A button that says "Resend" to resend the selected message.
        """
        self.undelivered_frame = tk.Frame(self.root)
        self.undelivered_frame.pack()

        # say a label with "Welcome Back"
        self.welcome_back_label = tk.Label(
            self.undelivered_frame, text=f"Welcome back, {self.credentials}!"
        )
        self.welcome_back_label.pack()

        self.undelivered_label = tk.Label(
            self.undelivered_frame, text=f"You have {self.n_undelivered} new messages"
        )
        self.undelivered_label.pack()

        if self.n_undelivered:
            # put a number entry for number of messages to view
            self.undelivered_number_label = tk.Label(
                self.undelivered_frame, text="Enter number of messages to view:"
            )
            self.undelivered_number_label.pack()

            # from 0 to n_undelivered
            self.undelivered_number_entry = tk.Entry(self.undelivered_frame)
            self.undelivered_number_entry.pack()

            # submit button
            self.undelivered_number_button = tk.Button(
                self.undelivered_frame,
                text="Submit",
                command=lambda: [
                    (
                        self.send_undelivered_request(
                            self.undelivered_number_entry.get()
                        )
                        if self.undelivered_number_entry.get()
                        else None
                    )
                ],
            )
            self.undelivered_number_button.pack()

            # out of range warning
            self.out_of_range_warning_label = tk.Label(
                self.undelivered_frame,
                text=f"Please enter a number between 0 and {self.n_undelivered}",
            )

            # listbox with undelivered messages
            self.undelivered_listbox = tk.Listbox(self.undelivered_frame)
            for message in self.undelivered_messages:
                self.undelivered_listbox.insert(tk.END, message)
            self.undelivered_listbox.pack()

        else:
            self.go_home_button = tk.Button(
                self.undelivered_frame,
                text="Go to Home",
                command=lambda: [self.destroy_undelivered(), self.setup_main()],
            )
            self.go_home_button.pack()

    def destroy_undelivered(self):
        """
        Destroy the undelivered screen.
        """
        self.undelivered_frame.destroy()

    def setup_register(self):
        """
        Set up the register screen.

        Has:
        - A label that says "Enter your username - reg:"
        - An entry for the user to enter their username.
        - A label that says "Enter your password - reg:"
        - An entry for the user to enter their password.
        - A label that says "Confirm your password - reg:"
        - An entry for the user to confirm their password.
        - A button that says "Register" to submit the registration.
        - A label that says "Passwords do not match" that is hidden by default.
        - A label that says "Username already exists" that is hidden by default.
        """
        self.register_frame = tk.Frame(self.root)
        self.register_frame.pack()

        self.register_label = tk.Label(
            self.register_frame, text=f"Username not found: please register"
        )
        self.register_label.pack()

        self.register_username_label = tk.Label(
            self.register_frame, text="Enter a username:"
        )
        self.register_username_label.pack()
        self.register_entry = tk.Entry(self.register_frame)
        self.register_entry.pack()
        self.register_password_label = tk.Label(
            self.register_frame, text="Choose your password:"
        )
        self.register_password_label.pack()
        self.register_password_entry = tk.Entry(self.register_frame)
        self.register_password_entry.pack()

        self.register_button = tk.Button(
            self.register_frame,
            text="Register",
            command=lambda: (
                self.send_logreg_request(  # KG: design choice for empty strings?
                    chat_pb2.REGISTER,
                    self.register_entry.get(),
                    self.register_password_entry.get(),
                )
                if self.register_entry.get() and self.register_password_entry.get()
                else None
            ),
        )
        self.register_button.pack()
        # self.register_passwords_do_not_match_label = tk.Label(
        #     self.register_frame, text="Passwords do not match"
        # )

        self.back_button_register = tk.Button(
            self.register_frame,
            text="Back",
            command=lambda: [self.destroy_register(), self.setup_user_entry()],
        )
        self.back_button_register.pack()

        self.register_username_exists_label = tk.Label(
            self.register_frame, text="Username already exists"
        )

    def destroy_register(self):
        """
        Destroy the register screen.
        """
        self.register_frame.destroy()

    def setup_main(self):
        """
        Main is set up into 3 components.

        On the left side is a list of all available users.
        - This is a listbox that is populated with all users.]
        - You can click on a user and click "Message" to start a chat with them.

        In the middle is the chat window.
        - This is a text widget that displays the chat history.
        - It is read-only.

        On the right side is the chat entry and settings.
        - It has a text entry for typing messages and a button under that says "send".
        - There is a button that says "Settings" at the bottom opens a new window.
        """
        self.main_frame = tk.Frame(self.root)
        self.main_frame.pack()

        self.loaded_messages = []

        self.logged_in_label = tk.Label(
            self.main_frame, text=f"Logged in as {self.credentials}"
        )
        self.logged_in_label.pack()

        self.users_frame = tk.Frame(self.main_frame)
        self.users_frame.pack(side=tk.LEFT)
        self.users_label = tk.Label(self.users_frame, text="Users")
        self.users_label.pack()

        self.users_listbox = tk.Listbox(self.users_frame)
        for user in self.users:
            self.users_listbox.insert(tk.END, user)

        self.users_listbox.pack()

        self.message_button = tk.Button(
            self.users_frame,
            text="Message",
            command=lambda: self.send_chat_load_request(
                self.users_listbox.get(tk.ACTIVE)
            ),
        )
        self.message_button.pack(side=tk.LEFT)

        self.ping_frame = tk.Frame(self.main_frame)
        self.ping_frame.pack(side=tk.BOTTOM)

        self.incoming_pings_label = tk.Label(self.ping_frame, text="Incoming Pings")
        self.incoming_pings_label.pack()
        self.incoming_pings_listbox = tk.Listbox(self.ping_frame)
        self.incoming_pings_listbox.pack()

        self.chat_frame = tk.Frame(self.main_frame)
        self.chat_frame.pack(side=tk.TOP)

        self.chat_text = tk.Listbox(self.chat_frame)

        self.chat_text.pack()

        # add text to chat frame
        for message in self.loaded_messages:
            self.chat_text.insert(tk.END, f"{message[0]}: {message[2]}\n")

        self.delete_message_button = tk.Button(
            self.chat_frame,
            text="Delete Message",
            command=lambda: (
                [self.send_delete_message_request(self.chat_text.curselection()[0] - 1)]
                if self.chat_text.curselection()
                else None
            ),
        )
        self.delete_message_button.pack()

        self.chat_entry_frame = tk.Frame(self.main_frame)
        self.chat_entry_frame.pack(side=tk.RIGHT)
        self.chat_entry = tk.Entry(self.chat_entry_frame)
        self.chat_entry.pack()
        self.send_button = tk.Button(
            self.chat_entry_frame,
            text="Send",
            command=lambda: [self.send_message_request(self.chat_entry.get())],
        )
        self.send_button.pack()
        self.settings_button = tk.Button(
            self.chat_entry_frame,
            text="Settings",
            command=lambda: [self.destroy_main(), self.setup_settings()],
        )
        self.settings_button.pack()

    def destroy_main(self):
        """
        Destroy the main screen.
        """
        self.main_frame.destroy()

    def setup_settings(self, failed=False):
        """
        Set up the settings screen.

        Has a button that says "Delete Account" that opens a new window.

        Parameters
        ----------
        failed : bool
            Whether the delete failed. If so, show a label that says "Failed to delete account, password incorrect".
        """
        self.settings_frame = tk.Frame(self.root)
        self.settings_frame.pack()

        self.connected_to = None

        if failed:
            self.delete_failed_label = tk.Label(
                self.settings_frame, text="Failed to delete account, password incorrect"
            )
            self.delete_failed_label.pack()

        self.delete_label = tk.Label(
            self.settings_frame,
            text="Are you sure you want to delete your account?\n(Enter password to confirm)",
        )
        self.delete_label.pack()

        self.confirm_password_label = tk.Label(
            self.settings_frame, text="Enter your password:"
        )
        self.confirm_password_label.pack()

        self.confirm_password_entry = tk.Entry(self.settings_frame)
        self.confirm_password_entry.pack()

        self.delete_button = tk.Button(
            self.settings_frame,
            text="Delete",
            command=lambda: (
                self.send_delete_request(self.confirm_password_entry.get())
                if self.confirm_password_entry.get()
                else None
            ),
        )
        self.delete_button.pack()
        self.cancel_button = tk.Button(
            self.settings_frame,
            text="Cancel",
            command=lambda: [self.destroy_settings(), self.setup_main()],
        )
        self.cancel_button.pack()

    def destroy_settings(self):
        """
        Destroy the settings screen.
        """
        self.settings_frame.destroy()

    def setup_deleted(self):
        """
        Set up the screen that shows the account has been deleted.
        """
        self.deleted_frame = tk.Frame(self.root)
        self.deleted_frame.pack()

        self.deleted_label = tk.Label(
            self.deleted_frame, text="Account successfully deleted."
        )
        self.deleted_label.pack()

        self.go_home_button = tk.Button(
            self.deleted_frame,
            text="Go to Home",
            command=lambda: [self.destroy_deleted(), self.setup_user_entry()],
        )
        self.go_home_button.pack()

    def destroy_deleted(self):
        """
        Destroy the deleted screen.
        """
        self.deleted_frame.destroy()

    def rerender_messages(self):
        """
        Rerender the messages in the chat window.
        Needs to be called whenever new messages are received or sent.
        """
        self.chat_text.delete(0, tk.END)
        if self.connected_to:
            self.chat_text.insert(tk.END, f"Messages with {self.connected_to}\n")
        for message in self.loaded_messages:
            self.chat_text.insert(tk.END, f"{message[0]}: {message[2]}\n")

    def rerender_pings(self):
        """
        Rerender the pings in the ping windows.
        Needs to be called whenever new pings are received.
        """
        self.incoming_pings_listbox.delete(0, tk.END)

        for ping in self.incoming_pings:
            self.incoming_pings_listbox.insert(tk.END, f"{ping[0]}: {ping[1]}")

    def rerender_users(self):
        """
        Rerender the users in the users listbox.
        Needs to be called whenever new users are received.
        """
        self.users_listbox.delete(0, tk.END)
        for user in self.users:
            self.users_listbox.insert(tk.END, user)

    def rerender_undelivered(self):
        """
        Rerender the undelivered messages in the undelivered listbox.
        Needs to be called whenever new undelivered messages are received.
        """
        self.undelivered_listbox.delete(0, tk.END)
        for message in self.undelivered_messages:
            self.undelivered_listbox.insert(tk.END, f"{message[0]}: {message[2]}")

        # remove submit button
        self.undelivered_number_button.pack_forget()

        # add "Go to Home" button
        self.go_home_button = tk.Button(
            self.undelivered_frame,
            text="Go to Home",
            command=lambda: [self.destroy_undelivered(), self.setup_main()],
        )
        self.go_home_button.pack()


"""
The rest of the code is for setting up the connection and running the client.
"""


if len(sys.argv) != 3:
    logging.error("Usage: python client.py <host> <port>")
    sys.exit(1)

host = sys.argv[1]
port = int(sys.argv[2])

if __name__ == "__main__":
    client_ui = ClientUI()
