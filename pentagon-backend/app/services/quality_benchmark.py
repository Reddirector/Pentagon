"""Output Quality Evaluation and 100-Point Benchmark Engine for Pentagon.

Strictly benchmarks generated deliverables (HTML websites, web apps, presentations)
across 5 critical dimensions:
  1. Semantic HTML & Document Architecture (20 points)
  2. Visual Polish & CSS Design System (20 points)
  3. Responsive Layout & Mobile Adaptability (20 points)
  4. Functional Interactivity & JavaScript (20 points)
  5. Domain Relevance & Content Density (20 points)

Total: 100 Points. Passing threshold is >= 95 points, benchmark target is 100/100.
"""

from __future__ import annotations

import re
from typing import Any


def evaluate_website_quality(html: str, expected_title: str | None = None, expected_topic: str | None = None) -> dict[str, Any]:
    """Score an HTML website deliverable against the strict 100-point Pentagon Benchmark.
    
    Returns a dictionary containing total_score, pass/fail status, and breakdown by dimension.
    """
    if isinstance(html, bytes):
        html = html.decode("utf-8", errors="replace")
    
    lower = html.lower()
    score_breakdown: dict[str, int] = {
        "semantic_html": 0,
        "visual_design_system": 0,
        "responsive_layout": 0,
        "interactivity_js": 0,
        "topic_relevance_and_density": 0,
    }
    feedback: list[str] = []

    # -------------------------------------------------------------------------
    # Dimension 1: Semantic HTML & Document Architecture (20 points)
    # -------------------------------------------------------------------------
    p1 = 0
    # 1.1 Complete DOCTYPE (4 pts)
    if "<!doctype html>" in lower:
        p1 += 4
    else:
        feedback.append("Missing <!DOCTYPE html> declaration (-4)")

    # 1.2 HTML element with lang (4 pts)
    if re.search(r"<html[^>]*lang=[\"'][a-zA-Z-]+[\"']", lower):
        p1 += 4
    elif "<html" in lower:
        p1 += 2
        feedback.append("Missing lang attribute on <html> (-2)")
    else:
        feedback.append("Missing <html> tag (-4)")

    # 1.3 Proper <head> with meta charset and <title> (4 pts)
    has_meta_charset = "charset=" in lower
    has_title = "<title>" in lower and "</title>" in lower and len(re.findall(r"<title>[\s\S]*?</title>", lower)[0]) > 8
    if has_meta_charset and has_title:
        p1 += 4
    elif has_meta_charset or has_title:
        p1 += 2
        feedback.append("Incomplete <head> metadata (-2)")
    else:
        feedback.append("Missing meta charset or title (-4)")

    # 1.4 Structured landmarks: nav/header, main, section/article, footer (4 pts)
    landmarks = [tag for tag in ["<nav", "<header", "<main", "<section", "<footer"] if tag in lower]
    if len(landmarks) >= 4:
        p1 += 4
    elif len(landmarks) >= 2:
        p1 += 2
        feedback.append("Sparse semantic landmark tags (-2)")
    else:
        feedback.append("Missing semantic landmark tags (-4)")

    # 1.5 Proper heading hierarchy: h1 and (h2 or h3) (4 pts)
    has_h1 = "<h1" in lower
    has_subheadings = "<h2" in lower or "<h3" in lower
    if has_h1 and has_subheadings:
        p1 += 4
    elif has_h1:
        p1 += 2
        feedback.append("Missing h2/h3 subheading hierarchy (-2)")
    else:
        feedback.append("Missing h1 primary heading (-4)")

    score_breakdown["semantic_html"] = p1

    # -------------------------------------------------------------------------
    # Dimension 2: Visual Polish & CSS Design System (20 points)
    # -------------------------------------------------------------------------
    p2 = 0
    # 2.1 CSS Custom Properties / Design Tokens (:root, --var) (5 pts)
    if ":root" in lower and "--" in lower:
        p2 += 5
    elif "--" in lower or "var(" in lower:
        p2 += 3
        feedback.append("Limited CSS variable design tokens (-2)")
    else:
        feedback.append("Missing CSS custom properties design tokens (-5)")

    # 2.2 Dark & Light Theme System (prefers-color-scheme or theme toggle) (5 pts)
    if "prefers-color-scheme" in lower or "data-theme" in lower or "dark-theme" in lower or "dark-mode" in lower:
        p2 += 5
    elif "rgba(" in lower and "#" in lower:
        p2 += 3
        feedback.append("Lacks dynamic dark/light theme tokens (-2)")
    else:
        feedback.append("No dark/light theme support (-5)")

    # 2.3 Visual Polish: Shadows, Transitions, Borders, Border-radius (5 pts)
    has_shadow = "box-shadow:" in lower or "--shadow" in lower
    has_transition = "transition:" in lower or "transition " in lower
    has_radius = "border-radius:" in lower or "--radius" in lower
    polish_count = sum([has_shadow, has_transition, has_radius])
    if polish_count == 3:
        p2 += 5
    elif polish_count >= 1:
        p2 += 3
        feedback.append("Partial visual polish styling (-2)")
    else:
        feedback.append("Missing modern UI shadows and transitions (-5)")

    # 2.4 Modern Typography & Layout System (font-family, flex/grid) (5 pts)
    has_typography = "font-family:" in lower
    has_layout_engine = "display: flex" in lower or "display: grid" in lower or "display:flex" in lower or "display:grid" in lower
    if has_typography and has_layout_engine:
        p2 += 5
    elif has_typography or has_layout_engine:
        p2 += 3
        feedback.append("Incomplete typography or modern layout rules (-2)")
    else:
        feedback.append("Missing typography and flex/grid rules (-5)")

    score_breakdown["visual_design_system"] = p2

    # -------------------------------------------------------------------------
    # Dimension 3: Responsive Layout & Mobile Adaptability (20 points)
    # -------------------------------------------------------------------------
    p3 = 0
    # 3.1 Mobile Viewport Meta (5 pts)
    if '<meta name="viewport"' in lower or "<meta name='viewport'" in lower:
        p3 += 5
    else:
        feedback.append("Missing mobile viewport meta tag (-5)")

    # 3.2 Responsive CSS Media Queries (@media (max-width / min-width)) (5 pts)
    media_queries = len(re.findall(r"@media\s*\([^)]+\)", lower))
    if media_queries >= 2:
        p3 += 5
    elif media_queries >= 1:
        p3 += 4
    else:
        feedback.append("Missing responsive @media queries (-5)")

    # 3.3 Responsive Grid or Flex Columns (5 pts)
    has_grid_or_columns = (
        "grid-template-columns" in lower
        or "flex-wrap: wrap" in lower
        or "flex-wrap:wrap" in lower
        or "gap:" in lower
    )
    if has_grid_or_columns:
        p3 += 5
    else:
        feedback.append("Missing responsive fluid grid/column layout (-5)")

    # 3.4 Mobile Navigation or Adaptive Controls (5 pts)
    has_mobile_nav = (
        "menu-toggle" in lower
        or "hamburger" in lower
        or "nav-toggle" in lower
        or "mobile-menu" in lower
        or ("@media" in lower and "nav" in lower and "flex-direction" in lower)
    )
    if has_mobile_nav:
        p3 += 5
    else:
        p3 += 2
        feedback.append("Lacks mobile menu navigation adapter (-3)")

    score_breakdown["responsive_layout"] = p3

    # -------------------------------------------------------------------------
    # Dimension 4: Functional Interactivity & JavaScript (20 points)
    # -------------------------------------------------------------------------
    p4 = 0
    # 4.1 Script Tag Present with Executable JavaScript (5 pts)
    has_script = "<script" in lower and "</script>" in lower
    if has_script:
        p4 += 5
    else:
        feedback.append("Missing script element (-5)")

    # 4.2 Event Listeners or Direct Event Binding (5 pts)
    has_events = (
        "addeventlistener" in lower
        or "onclick=" in lower
        or "onsubmit=" in lower
        or "oninput=" in lower
        or "onchange=" in lower
    )
    if has_events:
        p4 += 5
    else:
        feedback.append("Missing event listeners or interactive hooks (-5)")

    # 4.3 Stateful Feature: Filter, Toggle, Tabs, or Calculator Engine (5 pts)
    has_stateful_logic = (
        ("filter" in lower and ("cards" in lower or "items" in lower or "active" in lower))
        or ("modal" in lower and ("display" in lower or "open" in lower))
        or ("tabs" in lower or "accordion" in lower)
        or ("calc" in lower or "savings" in lower or "slider" in lower)
        or ("theme" in lower and "toggle" in lower)
    )
    if has_stateful_logic:
        p4 += 5
    else:
        feedback.append("Lacks stateful user interactivity logic (-5)")

    # 4.4 Functional Form or Interactive Feedback with Toast/Notification (5 pts)
    has_feedback = (
        "toast" in lower
        or "confirmation" in lower
        or "alert" in lower
        or "style.display = 'block'" in lower
        or "style.display='block'" in lower
        or "innertext" in lower
        or "innerhtml" in lower
    )
    has_no_todos = "todo" not in lower and "/* add javascript */" not in lower
    if has_feedback and has_no_todos:
        p4 += 5
    elif has_feedback:
        p4 += 3
        feedback.append("Contains placeholder TODO comments in script (-2)")
    else:
        feedback.append("Missing interactive feedback or toast confirmation (-5)")

    score_breakdown["interactivity_js"] = p4

    # -------------------------------------------------------------------------
    # Dimension 5: Domain Relevance & Content Density (20 points)
    # -------------------------------------------------------------------------
    p5 = 0
    # 5.1 Substantial Content Density (> 1,200 chars text content) (5 pts)
    plain_text = re.sub(r"<[^>]+>", " ", html)
    plain_text = re.sub(r"\s+", " ", plain_text).strip()
    if len(plain_text) >= 1000:
        p5 += 5
    elif len(plain_text) >= 500:
        p5 += 3
        feedback.append("Low text content density (-2)")
    else:
        feedback.append("Insufficient content density (-5)")

    # 5.2 Multiple Informational Cards / Items / Features (5 pts)
    card_matches = len(re.findall(r"class=[\"'][^\"']*(?:card|item|feature|plan|service|review)[^\"']*[\"']", lower))
    if card_matches >= 3:
        p5 += 5
    elif card_matches >= 1:
        p5 += 3
        feedback.append("Sparse feature cards (-2)")
    else:
        feedback.append("Missing feature cards (-5)")

    # 5.3 Title Grounding & Alignment (5 pts)
    if expected_title:
        title_words = [w.lower() for w in re.split(r"\W+", expected_title) if len(w) > 3]
        matched_words = [w for w in title_words if w in lower]
        if matched_words:
            p5 += 5
        else:
            p5 += 2
            feedback.append(f"Content does not clearly reference title keywords: {title_words} (-3)")
    else:
        p5 += 5

    # 5.4 Zero Inappropriate Template Leakage / Contamination (5 pts)
    # If the user asked for SaaS or Portfolio, ensure bakery terms didn't leak in!
    is_non_bakery_request = expected_title and not any(w in expected_title.lower() for w in ("bakery", "bread", "pastry", "loaf", "cake"))
    has_bakery_leakage = is_non_bakery_request and any(
        w in lower for w in ("pain au chocolat", "sourdough", "golden crust artisanal bakery", "stone hearth")
    )
    if not has_bakery_leakage:
        p5 += 5
    else:
        feedback.append("CRITICAL: Unrelated bakery template leaked into deliverable (-5)")

    score_breakdown["topic_relevance_and_density"] = p5

    total_score = sum(score_breakdown.values())
    passed = total_score >= 95

    return {
        "total_score": total_score,
        "passed": passed,
        "breakdown": score_breakdown,
        "feedback": feedback,
        "char_count": len(html),
        "text_density": len(plain_text),
    }
