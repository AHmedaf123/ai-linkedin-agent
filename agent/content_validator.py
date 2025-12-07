"""
Content quality validator for LinkedIn posts.
Validates posts before publishing to ensure they meet quality standards.
"""

import re
from typing import Dict, List, Tuple


def validate_formatting(text: str) -> Tuple[bool, List[str]]:
    """Validate that post has no formatting artifacts."""
    issues = []
    
    formatting_symbols = ['**', '__', '##', '- ', '* ', '~~~', '```']
    for symbol in formatting_symbols:
        if symbol in text:
            issues.append(f"Contains formatting symbol: {symbol}")
    
    structural_labels = ['Hook:', 'Context:', 'CTA:', 'Insight:', 'Value:', 'Story:', 'Call to Action:']
    for label in structural_labels:
        if label in text:
            issues.append(f"Contains structural label: {label}")
    
    return len(issues) == 0, issues


def validate_length(text: str) -> Tuple[bool, List[str]]:
    """Validate post length is appropriate for LinkedIn."""
    issues = []
    
    words = len(text.split())
    if words < 50:
        issues.append(f"Too short: {words} words (minimum 50)")
    elif words > 300:
        issues.append(f"Too long: {words} words (maximum 300)")
    
    chars = len(text)
    if chars > 1300:
        issues.append(f"Exceeds character limit: {chars} characters (maximum 1300)")
    
    return len(issues) == 0, issues


def validate_hashtags(hashtags: List[str], text: str) -> Tuple[bool, List[str]]:
    """Validate hashtag quality and placement."""
    issues = []
    
    if len(hashtags) < 3:
        issues.append(f"Too few hashtags: {len(hashtags)} (minimum 3)")
    elif len(hashtags) > 6:
        issues.append(f"Too many hashtags: {len(hashtags)} (maximum 6)")
    
    for tag in hashtags:
        if not tag.startswith('#'):
            issues.append(f"Invalid hashtag format: {tag}")
        elif len(tag) <= 2:
            issues.append(f"Hashtag too short: {tag}")
    
    hashtags_lower = [h.lower() for h in hashtags]
    if len(set(hashtags_lower)) != len(hashtags_lower):
        issues.append("Contains duplicate hashtags")
    
    body_lines = text.split('\n\n')
    if len(body_lines) > 0:
        last_section = body_lines[-1]
        hashtag_pattern = r'#\w+'
        tags_in_body = re.findall(hashtag_pattern, text)
        
        if tags_in_body and not all(tag in last_section for tag in tags_in_body):
            issues.append("Hashtags not properly placed at end")
    
    return len(issues) == 0, issues


def validate_engagement_potential(text: str) -> Tuple[bool, List[str]]:
    """Validate post has engagement elements."""
    issues = []
    
    if '?' not in text:
        issues.append("No question to invite engagement")
    
    sentences = [s.strip() for s in re.split(r'[.!?]', text) if s.strip()]
    if len(sentences) < 3:
        issues.append(f"Too few sentences: {len(sentences)} (minimum 3 for good flow)")
    
    lines = [l for l in text.splitlines() if l.strip()]
    max_line_length = max((len(l) for l in lines), default=0)
    if max_line_length > 150:
        issues.append(f"Has very long line ({max_line_length} chars) - hurts scannability")
    
    return len(issues) == 0, issues


def validate_seo_score(seo_score: int, threshold: int = 80) -> Tuple[bool, List[str]]:
    """Validate SEO score meets minimum threshold."""
    issues = []
    
    if seo_score < threshold:
        issues.append(f"SEO score {seo_score} below threshold {threshold}")
    
    return len(issues) == 0, issues


def validate_content_value(text: str) -> Tuple[bool, List[str]]:
    """Validate post provides educational value and specific insights."""
    issues = []
    
    # Check for specific data points
    import re
    numbers = re.findall(r'\d+\.?\d*%|\d+x|\d+\.\d+|\d{2,}', text)
    if len(numbers) < 2:
        issues.append(f"Insufficient data points: {len(numbers)} (minimum 2 required for educational value)")
    
    # Check for overly generic/vague language
    generic_indicators = [
        "evolving rapidly", "rapidly evolving", "exciting", "innovative", 
        "cutting-edge", "balance innovation", "start small"
    ]
    generic_count = sum(1 for phrase in generic_indicators if phrase.lower() in text.lower())
    if generic_count > 1:
        issues.append(f"Over-reliance on generic phrases: {generic_count} detected")
    
    # Ensure post provides insights, not just questions
    question_count = text.count("?")
    statement_count = text.count(".") + text.count("!")
    if question_count > 0 and question_count >= statement_count:
        issues.append("Post is mostly questions without providing concrete insights")
    
    # Check for technical specificity
    technical_patterns = r'\b(model|algorithm|framework|library|dataset|architecture|training|API|version \d+)\b'
    technical_terms = re.findall(technical_patterns, text, re.IGNORECASE)
    if len(technical_terms) < 1:
        issues.append("Lacks technical specificity - no frameworks, models, or specific tools mentioned")
    
    return len(issues) == 0, issues


def validate_post(post: Dict, seo_threshold: int = 80) -> Tuple[bool, Dict[str, List[str]]]:
    """
    Comprehensive post validation.
    
    Returns:
        Tuple of (is_valid, issues_by_category)
    """
    all_issues = {}
    
    body = post.get('body', '')
    hashtags = post.get('hashtags', [])
    seo_score = post.get('seo_score', 0)
    
    valid_format, format_issues = validate_formatting(body)
    if not valid_format:
        all_issues['formatting'] = format_issues
    
    valid_length, length_issues = validate_length(body)
    if not valid_length:
        all_issues['length'] = length_issues
    
    valid_tags, tag_issues = validate_hashtags(hashtags, body)
    if not valid_tags:
        all_issues['hashtags'] = tag_issues
    
    valid_engagement, engagement_issues = validate_engagement_potential(body)
    if not valid_engagement:
        all_issues['engagement'] = engagement_issues
    
    valid_seo, seo_issues = validate_seo_score(seo_score, seo_threshold)
    if not valid_seo:
        all_issues['seo'] = seo_issues
    
    valid_value, value_issues = validate_content_value(body)
    if not valid_value:
        all_issues['content_value'] = value_issues
    
    is_valid = len(all_issues) == 0
    
    return is_valid, all_issues


def get_validation_summary(issues: Dict[str, List[str]]) -> str:
    """Get a human-readable summary of validation issues."""
    if not issues:
        return "✓ All validations passed"
    
    summary_lines = ["Validation Issues Found:"]
    for category, issue_list in issues.items():
        summary_lines.append(f"\n{category.upper()}:")
        for issue in issue_list:
            summary_lines.append(f"  - {issue}")
    
    return "\n".join(summary_lines)
