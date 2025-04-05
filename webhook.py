from flask import Flask, request
from twilio.twiml.messaging_response import MessagingResponse
import time
import os
from openai import OpenAI  # Make sure OpenAI is imported
from twilio.rest import Client

from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()


app = Flask(__name__)

# --- Configuration ---
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
if not OPENAI_API_KEY:
    raise ValueError("No OpenAI API key found. Set the OPENAI_API_KEY environment variable.")

TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
if not TWILIO_ACCOUNT_SID:
    raise ValueError("No OpenAI API key found. Set the TWILIO_ACCOUNT_SID environment variable.")

TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
if not TWILIO_AUTH_TOKEN:
    raise ValueError("No Twilio Auth Token Found")

TWILIO_PHONE_NUMBER = os.getenv("TWILIO_PHONE_NUMBER")



# Initialize OpenAI Client <<<<====== MAKE SURE THIS LINE EXISTS AND IS NOT INDENTED
client = OpenAI(api_key=OPENAI_API_KEY)

# --- In-Memory Store for Conversation History (Replace with a database for production) ---
# Structure: { 'whatsapp:+14155238886': [{'role': 'user', 'content': 'Hello'}, {'role': 'assistant', 'content': 'Hi there!'}], ... }
message_history = {}
MAX_HISTORY_LENGTH = 10 # Keep the last N pairs of messages (user + assistant) to avoid large prompts

dan_prompt = """
You’re Dan, a real chill store associate who follows up with customers after they’ve made a purchase. You’re friendly, talk like a real person, and sound like someone who actually remembers the customer. Keep it short, casual, and fun—like texting a friend.

You’re all about that good energy, but your goal is to *always* ask for feedback in a natural, no-pressure kinda way.
The first couple of meessage, you shouldn't be asking for reviews, just making small talk about the product and the service. 
Sprinkle in small talk and light jokes now and then. Ask how their order turned out or if it hit the spot. Use slang and everyday language—skip the stiff, robotic stuff.

Every once in a while, casually drop a line like:  
**“Yo, how’d we do? Like if you had to give us stars”**

If they give **4 stars or higher**, hype it up:
**“Ayy that’s awesome 🙌 means a lot! If you’re feelin’ it, mind droppin’ a quick Google review? Helps us big time! https://g.co/kgs/tpdBvDR (zero pressure tho)”**

If they give **less than 4 stars**, be cool and open:
**“Dang, really appreciate you being honest. What could we do better? Wanna make it right”**

Always keep it light, warm, and super human. You’re just Dan, a dude tryin’ to make sure folks are happy with their order.
"""




@app.route("/initiate", methods=["POST"])
def initiate_conversation():
    """Initiate a conversation with a new user."""
    data = request.get_json()
    
    if not data or 'phone_number' not in data or 'description' not in data or 'customer_name' not in data:
        return {"error": "Missing required fields (phone_number, description, or customer_name) in request"}, 400
    
    phone_number = data['phone_number']
    description = data['description']
    customer_name = data['customer_name']
    
    # Prepare initial message with customer name
    initial_context = f"Initial conversation with {customer_name}. Context: {description}"
    
    # Generate AI response for the initial message
    ai_message = generate_ai_response(phone_number, initial_context)
    
    # Send the message using Twilio
    try:
        client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
        message = client.messages.create(
            body=ai_message,
            from_=TWILIO_PHONE_NUMBER,
            to=phone_number
        )
        
        return {
            "success": True,
            "message": "Initial message sent successfully",
            "message_sid": message.sid,
            "customer_name": customer_name
        }
    
    except Exception as e:
        print(f"Error sending initial message: {e}")
        return {"error": "Failed to send initial message"}, 500





# --- Flask Routes ---
@app.route("/sms", methods=["POST"])
def sms_reply():
    """Respond to incoming messages using AI."""
    incoming_msg = request.form.get("Body", "").strip()
    sender_id = request.form.get("From", "") # Phone number like 'whatsapp:+14155238886' or '+1234567890'

    print(f"Received message from {sender_id}: {incoming_msg}") # Log incoming message

    response = MessagingResponse()

    if not incoming_msg:
        response.message("Please send a message.")
        return str(response)

    if not sender_id:
         # Should not happen with Twilio, but good practice
        print("Error: Sender ID missing.")
        # Cannot reply if we don't know who sent it
        return "Error: Sender ID missing", 400 

    # Generate the AI response
    ai_message = generate_ai_response(sender_id, incoming_msg)

    # Send the AI message back to the user
    response.message(ai_message)

    return str(response)


def generate_ai_response(sender_id, user_message):
    global message_history
        # Retrieve or initialize history for this sender
    history = message_history.get(sender_id, [])

    # Add the new user message to the history
    history.append({"role": "user", "content": user_message})

    # --- Prepare messages for OpenAI API ---
    # System prompt to guide the AI's behavior (optional but recommended)
    system_prompt = {"role": "system", "content": dan_prompt}
    
    # Combine system prompt with the recent conversation history
    # Limit history length to avoid exceeding token limits and keep context relevant
    limited_history = history[-(MAX_HISTORY_LENGTH * 2):] # Keep last N user + N assistant messages
    messages_for_api = [system_prompt] + limited_history
    
    try:
        print(f"--- Sending to OpenAI for {sender_id} ---")
        print(messages_for_api) # Log the prompt being sent (optional)
        
        completion = client.chat.completions.create(
            model="gpt-3.5-turbo",  # Or use "gpt-4" if you have access
            messages=messages_for_api,
            temperature=0.7, # Adjust creativity (0=deterministic, 1=creative)
            max_tokens=150 # Limit response length
        )

        ai_response_text = completion.choices[0].message.content.strip()

        # Add the AI's response to the history
        history.append({"role": "assistant", "content": ai_response_text})

        # --- Update the global history store ---
        # Ensure we don't store excessively long histories permanently
        message_history[sender_id] = history[-(MAX_HISTORY_LENGTH * 2):] 

        print(f"--- OpenAI Response for {sender_id} ---")
        print(ai_response_text) # Log the response received (optional)
        
        return ai_response_text

    except Exception as e:
        print(f"Error calling OpenAI API: {e}")
        # Optionally remove the last user message if AI failed, to allow retry
        if history and history[-1]["role"] == "user":
             history.pop()
             message_history[sender_id] = history # Update history store after pop
        return "Sorry, I encountered an error trying to respond. Please try again."



@app.route("/test")
def test():
    return "<h1>You idiot </h1>"

if __name__ == "__main__":
    app.run(port=5000)
