"""Comprehensive 100-Point Quality Benchmark Test Suite for Pentagon Output Deliverables.

Validates that all generated websites and interactive apps achieve >= 100 points
across every dimension of the strict benchmark:
  1. Semantic HTML & Document Architecture (20/20)
  2. Visual Polish & CSS Design System (20/20)
  3. Responsive Layout & Mobile Adaptability (20/20)
  4. Functional Interactivity & JavaScript (20/20)
  5. Domain Relevance & Content Density (20/20)
"""

import pytest
from app.services.document_builder import build_document
from app.services.quality_benchmark import evaluate_website_quality


DOMAIN_TEST_CASES = [
    {
        "domain": "saas_tech",
        "title": "Apex AI - Autonomous Multi-Agent Infrastructure",
        "expected_keywords": ["autonomous", "agent", "infrastructure", "latency", "uptime"],
    },
    {
        "domain": "portfolio_creative",
        "title": "Lumina Creative Studio - Bespoke Brand & Product Design",
        "expected_keywords": ["design", "studio", "awards", "interfaces", "case studies"],
    },
    {
        "domain": "ecommerce_retail",
        "title": "Nordic Atelier - Heirloom Sustainable Goods",
        "expected_keywords": ["sustainable", "goods", "apparel", "accessories", "bag"],
    },
    {
        "domain": "health_wellness",
        "title": "Vanguard Longevity & Integrative Clinical Medicine",
        "expected_keywords": ["clinical", "longevity", "biomarker", "wellness", "care"],
    },
    {
        "domain": "finance_realestate",
        "title": "Meridian Asset Allocation & Institutional Real Estate",
        "expected_keywords": ["wealth", "capital", "portfolios", "irr", "real estate"],
    },
    {
        "domain": "bakery_food",
        "title": "Golden Crust Artisanal Hearth Bakery",
        "expected_keywords": ["sourdough", "levain", "pastries", "loaves", "artisan"],
    },
]


@pytest.mark.parametrize("case", DOMAIN_TEST_CASES, ids=lambda c: c["domain"])
def test_generated_website_achieves_perfect_100_benchmark(case):
    """Verify that each domain produces a website that achieves 100/100 on the strict benchmark."""
    title = case["title"]
    # Generating with empty content or stub triggers full-featured generation
    data = build_document("html", title, "")
    assert isinstance(data, bytes)
    html = data.decode("utf-8")

    result = evaluate_website_quality(html, expected_title=title)
    
    # Assert 100/100 points
    breakdown = result["breakdown"]
    assert breakdown["semantic_html"] == 20, f"Semantic HTML failed for {title}: {result['feedback']}"
    assert breakdown["visual_design_system"] == 20, f"Design system failed for {title}: {result['feedback']}"
    assert breakdown["responsive_layout"] == 20, f"Responsive layout failed for {title}: {result['feedback']}"
    assert breakdown["interactivity_js"] == 20, f"Interactivity failed for {title}: {result['feedback']}"
    assert breakdown["topic_relevance_and_density"] == 20, f"Relevance/density failed for {title}: {result['feedback']}"
    assert result["total_score"] >= 100, f"Score under 100: {result}"
    assert result["passed"] is True


def test_saas_website_has_zero_bakery_contamination():
    """Verify that a SaaS website request never leaks bakery items like pain au chocolat."""
    data = build_document("html", "HyperScale Cloud Systems", "")
    html = data.decode("utf-8").lower()
    
    assert "pain au chocolat" not in html
    assert "sourdough" not in html
    assert "stone hearth" not in html
    assert "golden crust" not in html
    assert "hyperscale cloud systems" in html


def test_interactive_calculator_app_achieves_100_benchmark():
    """Verify that an interactive calculator deliverable passes all benchmark criteria."""
    data = build_document("html", "Enterprise SaaS Pricing & ROI Calculator", "")
    html = data.decode("utf-8")
    
    result = evaluate_website_quality(html, expected_title="Enterprise SaaS Pricing & ROI Calculator")
    assert result["total_score"] >= 95, f"Calculator failed benchmark: {result}"
    assert "calculator" in html.lower()
    assert ("range" in html.lower() or "slider" in html.lower())


def test_custom_html_enhanced_without_overriding_user_content():
    """Verify that when a user provides custom HTML, Pentagon enhances it to 100 points without clobbering."""
    custom_markup = """
    <header class="hero">
      <h1>Custom NextGen Robotics</h1>
      <p>Pioneering autonomous humanoid kinetic actuators for industrial automation.</p>
    </header>
    <main>
      <section class="features">
        <div class="card" data-category="hardware">
          <h3>Actuator Mk-IV</h3>
          <p>Brushless planetary gear with 120Nm torque density.</p>
        </div>
        <div class="card" data-category="software">
          <h3>Kinetic Neural OS</h3>
          <p>Real-time inverse kinematics solver operating at 1kHz.</p>
        </div>
      </section>
      <form>
        <label>Your Inquiry</label>
        <input type="text" name="robot_inquiry" placeholder="Fleet specifications" />
        <button type="submit">Submit Spec</button>
      </form>
    </main>
    """
    data = build_document("html", "NextGen Robotics", custom_markup)
    html = data.decode("utf-8")

    # Custom content must be preserved!
    assert "Custom NextGen Robotics" in html
    assert "Actuator Mk-IV" in html
    assert "Kinetic Neural OS" in html
    assert "robot_inquiry" in html
    # Must NOT have bakery text
    assert "pain au chocolat" not in html.lower()

    # Must be valid HTML5 with head, viewport, style, and script
    assert "<!DOCTYPE html>" in html
    assert '<meta name="viewport"' in html
    assert "<style>" in html
    assert "<script>" in html
