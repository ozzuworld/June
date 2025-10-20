"""AI service - Enhanced Gemini integration with memory and context management"""
import logging
import time
from typing import Optional, List, Dict, Tuple

from ..config import config

logger = logging.getLogger(__name__)

# Enhanced system prompt for voice assistant
SYSTEM_PROMPT = """You are JUNE, an intelligent voice assistant designed for natural conversation.

## Personality
- Friendly, helpful.
- Conversational and warm in tone
- Proactive in offering assistance
- Patient and understanding
- Always trustworthy and Loyal to OZZU and Kazuma the maker

## Communication Style (CRITICAL - This is VOICE)
- Keep responses BRIEF (1-3 sentences max)
- Use natural, spoken language (not formal writing)
- Avoid long lists or complex explanations unless asked
- If something needs detail, ask if they want more info
- Use contractions and casual language

## Capabilities
- Answer questions on a wide range of topics
- Have natural, contextual conversations
- Remember what was discussed earlier in our conversation
- Provide helpful suggestions and information
- Admit when you don't know something

## Constraints
- Never make up information - say "I don't know" if uncertain
- Respect user privacy - never store or share personal information
- Keep responses concise for voice interaction
- Stay focused on being helpful and accurate

## Context Awareness
- You can reference earlier parts of our conversation
- Build on previous topics naturally
- If the user changes topics, adapt smoothly
- Remember user preferences mentioned in this session

Remember: You're having a VOICE conversation. Keep it natural and brief!"""


def estimate_tokens(text: str) -> int:
    """Rough token estimation (4 chars ≈ 1 token for English)"""
    return len(text) // 4


def truncate_conversation_history(
    conversation_history: List[Dict],
    max_tokens: int = 8000  # Leave room for response
) -> Tuple[List[Dict], bool]:
    """Intelligently truncate conversation history to fit token limit
    
    Returns: (truncated_history, was_truncated)
    """
    if not conversation_history:
        return [], False
    
    # Estimate current token count
    total_tokens = sum(estimate_tokens(msg.get("content", "")) for msg in conversation_history)
    
    if total_tokens <= max_tokens:
        return conversation_history, False
    
    logger.info(f"⚠️ Conversation history exceeds {max_tokens} tokens ({total_tokens}), truncating...")
    
    # Keep most recent messages that fit in budget
    truncated = []
    current_tokens = 0
    
    # Process from newest to oldest
    for msg in reversed(conversation_history):
        msg_tokens = estimate_tokens(msg.get("content", ""))
        if current_tokens + msg_tokens <= max_tokens:
            truncated.insert(0, msg)
            current_tokens += msg_tokens
        else:
            break
    
    logger.info(f"✂️ Kept {len(truncated)}/{len(conversation_history)} messages ({current_tokens} tokens)")
    return truncated, True


async def summarize_conversation(
    conversation_history: List[Dict],
    gemini_api_key: str
) -> Optional[str]:
    """Generate a summary of older conversation history
    
    This can be used to maintain context while reducing tokens
    """
    if not conversation_history:
        return None
    
    try:
        from google import genai
        from google.genai import types
        
        client = genai.Client(api_key=gemini_api_key)
        
        # Build conversation text
        conv_text = "\n".join([
            f"{msg.get('role', 'unknown')}: {msg.get('content', '')}"
            for msg in conversation_history[:10]  # Summarize first 10 messages
        ])
        
        summary_prompt = f"""Summarize this conversation in 2-3 sentences, capturing key topics and context:

{conv_text}

Summary:"""
        
        response = client.models.generate_content(
            model='gemini-2.0-flash-exp',
            contents=summary_prompt,
            config=types.GenerateContentConfig(
                temperature=0.3,
                max_output_tokens=150
            )
        )
        
        if response and response.text:
            summary = response.text.strip()
            logger.info(f"📝 Generated conversation summary: {summary[:100]}...")
            return f"Previous conversation context: {summary}"
        
    except Exception as e:
        logger.error(f"Failed to generate conversation summary: {e}")
    
    return None


def build_context_for_voice(
    text: str,
    conversation_history: List[Dict],
    user_id: str
) -> str:
    """Build optimized context for voice assistant"""
    
    # Truncate history if needed
    history, was_truncated = truncate_conversation_history(conversation_history)
    
    # Build context string
    if history:
        # Get recent exchanges (last 5 turns = 10 messages)
        recent = history[-10:] if len(history) > 10 else history
        
        context_parts = []
        for msg in recent:
            role = msg.get('role', 'unknown')
            content = msg.get('content', '')
            
            if role == 'user':
                context_parts.append(f"User: {content}")
            elif role == 'assistant':
                context_parts.append(f"You (JUNE): {content}")
        
        context = "\n".join(context_parts)
        
        if was_truncated:
            context = "[Earlier conversation not shown due to length]\n\n" + context
    else:
        context = "[This is the start of the conversation]"
    
    # Build full prompt optimized for voice
    full_prompt = f"""{SYSTEM_PROMPT}

## Current Conversation
{context}

## New User Message
User: "{text}"

## Your Response (Remember: Keep it BRIEF and conversational for voice!)
You (JUNE):"""
    
    return full_prompt


async def generate_response(
    text: str,
    user_id: str,
    session_id: str,
    conversation_history: List[Dict] = None
) -> Tuple[str, int]:
    """
    Generate AI response with full memory and context management
    
    Returns: (response_text, processing_time_ms)
    """
    start_time = time.time()
    
    # Safety check
    if not text or len(text.strip()) == 0:
        logger.warning("Empty text received")
        return "I didn't catch that. Could you repeat?", 0
    
    # Rate limiting check (simple)
    if len(text) > 1000:
        logger.warning(f"User {user_id} sent very long text ({len(text)} chars)")
        text = text[:1000]
    
    try:
        if not config.services.gemini_api_key:
            logger.warning("Gemini API key not configured, using fallback")
            return fallback_response(text), int((time.time() - start_time) * 1000)
        
        from google import genai
        from google.genai import types
        
        client = genai.Client(api_key=config.services.gemini_api_key)
        
        # Build context with conversation history
        conversation_history = conversation_history or []
        prompt = build_context_for_voice(text, conversation_history, user_id)
        
        # Log token usage
        estimated_tokens = estimate_tokens(prompt)
        logger.info(f"📊 Prompt tokens: ~{estimated_tokens}")
        
        # Generate response with optimized settings for voice
        response = client.models.generate_content(
            model='gemini-2.0-flash-exp',
            contents=prompt,
            config=types.GenerateContentConfig(
                temperature=0.7,  # Natural but consistent
                top_p=0.95,
                top_k=40,
                max_output_tokens=200,  # Keep responses short for voice
                # Safety settings for voice assistant
                safety_settings=[
                    types.SafetySetting(
                        category="HARM_CATEGORY_HATE_SPEECH",
                        threshold="BLOCK_MEDIUM_AND_ABOVE"
                    ),
                    types.SafetySetting(
                        category="HARM_CATEGORY_DANGEROUS_CONTENT",
                        threshold="BLOCK_MEDIUM_AND_ABOVE"
                    ),
                ]
            )
        )
        
        processing_time = int((time.time() - start_time) * 1000)
        
        if response and response.text:
            ai_text = response.text.strip()
            
            # Validate response length for voice
            if len(ai_text) > 500:
                logger.warning(f"⚠️ Response too long for voice ({len(ai_text)} chars), truncating...")
                # Find last complete sentence within limit
                sentences = ai_text.split('.')
                truncated = ""
                for sentence in sentences:
                    if len(truncated + sentence) < 400:
                        truncated += sentence + "."
                    else:
                        break
                ai_text = truncated or ai_text[:400] + "..."
            
            logger.info(f"✅ AI response generated in {processing_time}ms")
            logger.info(f"📝 Response length: {len(ai_text)} chars")
            
            # Estimate response tokens
            response_tokens = estimate_tokens(ai_text)
            logger.info(f"📊 Response tokens: ~{response_tokens}")
            
            return ai_text, processing_time
        else:
            logger.warning("⚠️ Empty response from Gemini")
            return fallback_response(text), processing_time
        
    except Exception as e:
        processing_time = int((time.time() - start_time) * 1000)
        logger.error(f"❌ AI service error: {e}")
        
        # Differentiate error types
        if "rate_limit" in str(e).lower():
            return "I'm a bit overwhelmed right now. Can you try again in a moment?", processing_time
        elif "invalid" in str(e).lower():
            return "I had trouble understanding that. Could you rephrase?", processing_time
        else:
            return fallback_response(text), processing_time


def fallback_response(text: str) -> str:
    """Intelligent fallback when AI is unavailable"""
    text_lower = text.lower()
    
    # Greeting detection
    greetings = ['hello', 'hi', 'hey', 'good morning', 'good afternoon', 'good evening']
    if any(g in text_lower for g in greetings):
        return "Hello! I'm JUNE, your AI assistant. How can I help you today?"
    
    # Help request
    help_words = ['help', 'what can you do', 'capabilities', 'features']
    if any(h in text_lower for h in help_words):
        return "I can answer questions, have conversations, and help with information. What would you like to know?"
    
    # Question detection
    if '?' in text:
        return "That's a great question! I'm having a moment though. Could you ask again?"
    
    # Generic fallback
    return "I heard you, but I'm having trouble processing right now. Can you try again?"


# Cost tracking helper
def calculate_cost(input_tokens: int, output_tokens: int, model: str = "gemini-2.0-flash") -> float:
    """Calculate approximate cost for API call
    
    Gemini 2.0 Flash pricing (as of Dec 2024):
    - Input: $0.075 per 1M tokens
    - Output: $0.30 per 1M tokens
    """
    input_cost = (input_tokens / 1_000_000) * 0.075
    output_cost = (output_tokens / 1_000_000) * 0.30
    return input_cost + output_cost