import grpc
import threading

import chat_pb2
import chat_pb2_grpc

def request_generator(username):
    # First, send a CONNECT message.
    yield chat_pb2.ChatRequest(action=chat_pb2.CONNECT, username=username)
    print("Commands:")
    print("  send <message>           -- send a message to the server")
    print("  notify <message>         -- broadcast a message to all users")
    print("  sendto <user> <message>  -- send a private message")
    print("  exit")
    while True:
        cmd = input("> ")
        if cmd.startswith("sendto "):
            parts = cmd.split(" ", 2)
            if len(parts) < 3:
                print("Usage: sendto <user> <message>")
                continue
            target, message = parts[1], parts[2]
            yield chat_pb2.ChatRequest(action=chat_pb2.SEND_TO, username=username, target=target, message=message)
        elif cmd.startswith("notify "):
            message = cmd[len("notify "):]
            yield chat_pb2.ChatRequest(action=chat_pb2.NOTIFY_ALL, username=username, message=message)
        elif cmd.startswith("send "):
            message = cmd[len("send "):]
            yield chat_pb2.ChatRequest(action=chat_pb2.SEND_MESSAGE, username=username, message=message)
        elif cmd.strip() == "exit":
            break

def run():
    channel = grpc.insecure_channel('localhost:50051')
    stub = chat_pb2_grpc.ChatServiceStub(channel)
    username = input("Enter your username: ").strip()
    responses = stub.Chat(request_generator(username))

    # Process responses in a separate thread.
    def read_responses():
        for resp in responses:
            print("Response:", resp.message)

    threading.Thread(target=read_responses, daemon=True).start()

    # Keep the main thread alive while the response thread runs.
    while True:
        try:
            pass
        except KeyboardInterrupt:
            break

if __name__ == '__main__':
    run()
