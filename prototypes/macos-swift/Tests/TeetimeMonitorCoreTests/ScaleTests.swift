@testable import TeetimeMonitorCore

func runScaleTests() {
    Harness.group("Scale") {
        testFactorsAreOrderedAndDistinct()
        testSmallIsIdentity()
        testScaledRounding()
        testSingletonReactsToOptionChange()
    }
}

/// The bug this whole feature had until it was fixed: the factors must actually
/// differ, or "changing scale" is silently a no-op again.
private func testFactorsAreOrderedAndDistinct() {
    let small = AppScaleOption.small.factor
    let medium = AppScaleOption.medium.factor
    let large = AppScaleOption.large.factor
    Harness.check("small < medium", small < medium)
    Harness.check("medium < large", medium < large)
    Harness.check("the difference is large enough to notice, not a rounding error", large - small > 0.3)
}

/// Direct request, 2026-09-19 ("make old large scale new medium scale, old
/// medium is now small, large needs to be extra large") -- .small, not .medium,
/// is now the "no scaling at all" tier (see AppScaleOption.factor's own
/// docstring), and AppScale's own default fallback moved to .small right along
/// with it so a fresh install still looks unchanged.
private func testSmallIsIdentity() {
    Harness.checkClose("small's factor is exactly 1.0 (an untouched install looks unchanged)",
                        AppScaleOption.small.factor, 1.0, tolerance: 1e-9)
}

private func testScaledRounding() {
    let scale = AppScale.shared
    scale.option = .small
    Harness.checkClose("small leaves a dimension unchanged", scale.scaled(42), 42, tolerance: 1e-9)
    scale.option = .large
    // Rounded to a whole point -- a fractional frame would make adjacent columns
    // disagree about their own edges.
    let scaled = scale.scaled(42)
    Harness.check("scaled(42) at large is a whole number", scaled == scaled.rounded())
    Harness.check("scaled(42) at large is actually larger", scaled > 42)
}

private func testSingletonReactsToOptionChange() {
    let scale = AppScale.shared
    scale.option = .small
    let smallResult = scale.scaled(100)
    scale.option = .large
    let largeResult = scale.scaled(100)
    Harness.check("the shared instance's own scaled() reflects the current option, not a cached one",
                   largeResult > smallResult)
    scale.option = .medium  // leave it as the harness found it for any test that runs after
}
