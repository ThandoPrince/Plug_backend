import re
from django.db.models import Q
from api.serviceProvidersDB.models import Service, ServiceKeyword, RiskLevel
from rapidfuzz import process, fuzz

def normalize_text(text: str) -> str:
    """Lowercase, remove punctuation, and collapse spaces."""
    if not text:
        return ""
    text = text.lower()
    text = re.sub(r"[^\w\s]", "", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()

def de_leet_text(text: str) -> str:
    """Converts leetspeak and collapses repeated characters (e.g., 'seeeex' -> 'sex')."""
    replacements = {
        '4': 'a', '@': 'a', '3': 'e', '1': 'i', '!': 'i', 
        '0': 'o', '5': 's', '$': 's', '7': 't', '+': 't', 
        '8': 'b', '9': 'g', '6': 'g'
    }
    text = text.lower()
    for char, replacement in replacements.items():
        text = text.replace(char, replacement)
    
    text = re.sub(r"[^a-zA-Z0-9\s]", "", text)
    text = re.sub(r'(.)\1+', r'\1', text) 
    return text

def check_for_prohibited_content(input_text: str, prohibited_list: list):
    """Checks for blocked words using exact, substring, and fuzzy matching."""
    cleaned_input = de_leet_text(input_text)
    input_words = cleaned_input.split()

    for word in input_words:
        # 1. Exact Match
        if word in prohibited_list:
            return True, word
        
        # 2. Fuzzy Match for typos (Score >= 85)
        if prohibited_list:
            match = process.extractOne(word, prohibited_list, scorer=fuzz.ratio)
            if match and match[1] >= 85:
                return True, match[0]

    return False, None

def analyze_service_submission(name: str, description: str = ""):
    """
    Analyzes submission to reject prohibited items or map to existing synonyms.
    """
    # 1. Fetch all active keywords once to avoid multiple DB hits
    all_keywords = ServiceKeyword.objects.filter(is_active=True).select_related(
        'service', 'service__service_group__category'
    )
    
    prohibited_list = [k.keyword for k in all_keywords if k.is_prohibited]
    
    # 2. Immediate Prohibited Check
    is_bad, matched_word = check_for_prohibited_content(f"{name} {description}", prohibited_list)
    if is_bad:
        return {
            "status": "rejected",
            "reason": f"Service violates marketplace policies (detected: {matched_word})."
        }

    # 3. Synonym Mapping Logic
    normalized_content = normalize_text(name)
    content_words = normalized_content.split()
    
    # Create map for allowed keywords
    allowed_keyword_map = {normalize_text(k.keyword): k for k in all_keywords if not k.is_prohibited}
    allowed_strings = list(allowed_keyword_map.keys())

    # Greedy search: check longest possible phrases first
    # This ensures "house painter" matches before "house" or "painter"
    for length in range(len(content_words), 0, -1):
        for i in range(len(content_words) - length + 1):
            phrase = " ".join(content_words[i:i + length])
            
            # Try Exact Match
            keyword_obj = allowed_keyword_map.get(phrase)
            
            # Try Fuzzy Match (Partial Ratio is better for "house paint" -> "house painter")
            if not keyword_obj and allowed_strings:
                match = process.extractOne(phrase, allowed_strings, scorer=fuzz.partial_ratio)
                if match and match[1] >= 90:
                    keyword_obj = allowed_keyword_map.get(match[0])

            if keyword_obj and keyword_obj.service:
                return {
                    "status": "mapped_existing",
                    "service": keyword_obj.service,
                    "risk_level": keyword_obj.service.service_group.category.risk_level
                }

    return {
        "status": "auto_approve",
        "risk_level": RiskLevel.LOW
    }

def validate_service_submission(name: str, description: str = ""):
    """Master validation function."""
    # Check for exact name match first
    existing = Service.objects.filter(service_name__iexact=name.strip()).first()
    if existing:
        return {"status": "exists", "service": existing}

    return analyze_service_submission(name, description)