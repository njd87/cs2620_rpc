import grpc
from concurrent import futures
import time
import queue
import threading

import chat_pb2
import chat_pb2_grpc

# Mapping from username to a queue that holds outgoing responses.
clients = {}

class ChatServiceServicer(chat_pb2_grpc.ChatServiceServicer):
    def Chat(self, request_iterator, context):
        username = None
        # Create a queue for sending responses to this client.
        client_queue = queue.Queue()

        # Function to handle incoming requests.
        def handle_requests():
            nonlocal username
            try:
                for req in request_iterator:
                    if req.action == chat_pb2.CONNECT:
                        username = req.username
                        clients[username] = client_queue
                        client_queue.put(chat_pb2.ChatResponse(success=True, message=f"Connected as {username}"))
                        print(f"{username} connected.")
                    elif req.action == chat_pb2.SEND_MESSAGE:
                        # Reply with "Received <message>".
                        client_queue.put(chat_pb2.ChatResponse(success=True, message=f"Received {req.message}"))
                    elif req.action == chat_pb2.NOTIFY_ALL:
                        # Broadcast the message to all connected clients.
                        broadcast = f"Broadcast from {username}: {req.message}"
                        for user_q in clients.values():
                            user_q.put(chat_pb2.ChatResponse(success=True, message=broadcast))
                    elif req.action == chat_pb2.SEND_TO:
                        target = req.target
                        if target in clients:
                            private = f"Private from {username}: {req.message}"
                            clients[target].put(chat_pb2.ChatResponse(success=True, message=private))
                        else:
                            client_queue.put(chat_pb2.ChatResponse(success=False, message=f"User {target} is not online"))
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
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    chat_pb2_grpc.add_ChatServiceServicer_to_server(ChatServiceServicer(), server)
    server.add_insecure_port('[::]:50051')
    server.start()
    print("Server started on port 50051")
    try:
        while True:
            time.sleep(86400)
    except KeyboardInterrupt:
        server.stop(0)

if __name__ == '__main__':
    serve()
