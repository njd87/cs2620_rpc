import tkinter as tk
from tkinter import simpledialog
import threading
import queue
import grpc

import chat_pb2
import chat_pb2_grpc

# A thread-safe queue for outgoing ChatRequests.
outgoing_queue = queue.Queue()

def request_generator():
    """Yield ChatRequests from the outgoing_queue."""
    while True:
        req = outgoing_queue.get()
        yield req

class ChatClientApp:
    def __init__(self, master, username):
        self.master = master
        self.username = username

        # Set up gRPC connection.
        self.channel = grpc.insecure_channel('localhost:50051')
        self.stub = chat_pb2_grpc.ChatServiceStub(self.channel)

        # Send a CONNECT message to register the username.
        outgoing_queue.put(chat_pb2.ChatRequest(
            action=chat_pb2.Action.CONNECT,
            username=self.username,
            message="",
            target=""
        ))

        # Start a background thread to process server responses.
        threading.Thread(target=self.handle_responses, daemon=True).start()

        # Build the tkinter UI.
        self.build_ui()

    def build_ui(self):
        self.master.title(f"Chat Client - {self.username}")

        # Text widget to display messages.
        self.text_display = tk.Text(self.master, height=20, width=60, state=tk.DISABLED)
        self.text_display.pack(padx=10, pady=10)

        # Frame for the message controls.
        control_frame = tk.Frame(self.master)
        control_frame.pack(padx=10, pady=5)

        # Radio buttons to select the message type.
        self.msg_type = tk.StringVar(value="send_message")
        tk.Radiobutton(control_frame, text="Send Message", variable=self.msg_type,
                       value="send_message", command=self.update_target_state).grid(row=0, column=0, padx=5)
        tk.Radiobutton(control_frame, text="Notify All", variable=self.msg_type,
                       value="notify_all", command=self.update_target_state).grid(row=0, column=1, padx=5)
        tk.Radiobutton(control_frame, text="Send To", variable=self.msg_type,
                       value="send_to", command=self.update_target_state).grid(row=0, column=2, padx=5)

        # Target username (only enabled when "Send To" is selected).
        self.target_label = tk.Label(control_frame, text="Target:")
        self.target_label.grid(row=1, column=0, padx=5, pady=5)
        self.target_entry = tk.Entry(control_frame)
        self.target_entry.grid(row=1, column=1, padx=5, pady=5)
        # Initially disable target input.
        self.target_entry.config(state=tk.DISABLED)

        # Entry field for the message.
        self.msg_entry = tk.Entry(control_frame, width=50)
        self.msg_entry.grid(row=2, column=0, columnspan=3, padx=5, pady=5)

        # Send button.
        tk.Button(control_frame, text="Send", command=self.send_message).grid(row=3, column=1, padx=5, pady=5)

    def update_target_state(self):
        """Enable the target entry only if 'Send To' is selected."""
        if self.msg_type.get() == "send_to":
            self.target_entry.config(state=tk.NORMAL)
        else:
            self.target_entry.delete(0, tk.END)
            self.target_entry.config(state=tk.DISABLED)

    def send_message(self):
        """Create a ChatRequest from the UI inputs and put it into the outgoing queue."""
        message = self.msg_entry.get().strip()
        if not message:
            return

        # Determine the action based on the selected radio button.
        if self.msg_type.get() == "send_message":
            action = chat_pb2.Action.SEND_MESSAGE
        elif self.msg_type.get() == "notify_all":
            action = chat_pb2.Action.NOTIFY_ALL
        elif self.msg_type.get() == "send_to":
            action = chat_pb2.Action.SEND_TO
        else:
            action = chat_pb2.Action.UNKNOWN

        target = self.target_entry.get().strip() if action == chat_pb2.Action.SEND_TO else ""
        req = chat_pb2.ChatRequest(
            action=action,
            username=self.username,
            target=target,
            message=message
        )
        outgoing_queue.put(req)
        self.msg_entry.delete(0, tk.END)

    def handle_responses(self):
        """Continuously receive responses from the server and display them in the text widget."""
        try:
            responses = self.stub.Chat(request_generator())
            for resp in responses:
                self.display_message(resp.message)
        except grpc.RpcError as e:
            self.display_message("Disconnected from server.")

    def display_message(self, msg):
        """Insert a message into the text widget."""
        self.text_display.config(state=tk.NORMAL)
        self.text_display.insert(tk.END, msg + "\n")
        self.text_display.config(state=tk.DISABLED)
        self.text_display.see(tk.END)

def main():
    root = tk.Tk()
    # Prompt the user for a username.
    username = simpledialog.askstring("Username", "Enter your username:", parent=root)
    if not username:
        return
    app = ChatClientApp(root, username)
    root.mainloop()

if __name__ == '__main__':
    main()
