"""
Just using this to test OSC functions
"""
from pythonosc.udp_client import SimpleUDPClient

ip = "127.0.0.1"
port = 1337

client = SimpleUDPClient(ip, port)  # Create client

# client.send_message("/time", [13, 25])
# client.send_message("/enable_random_glitch", 100)
# client.send_message("/set_color", [100,100,0])
# client.send_message("/brightness", [40, 1])
#client.send_message("/random_x_glitch", [1000, 4, 100])
#client.send_message("/x_positions", ['XXXX'])
# client.send_message("/time_dilation", 100)
# client.send_message("/increment_time", -20)
#client.send_message("/glitch_to", [12, 0])
client.send_message("/blink_all", 0)
