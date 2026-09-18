import SwiftUI

/// A macro-free stand-in for `@State` -- see README.md's own note on why: `@State` is
/// implemented as a macro now, and `SwiftUIMacros`'s plugin ships with Xcode, not the
/// Command Line Tools, so any view with real local state fails to compile here with
/// "external macro implementation type 'SwiftUIMacros.StateMacro' could not be found."
///
/// `ObservableObject`/`@Published`/`@StateObject` predate macros and build fine with
/// plain `swiftc` -- this wraps a single value in exactly that shape so a call site
/// reads almost like `@State` did: `@StateObject private var x = Box(false)`, then
/// `x.value` where you'd have written `x`, and `$x.value` where you'd have written
/// `$x` for a `Binding`.
final class Box<Value>: ObservableObject {
    @Published var value: Value
    init(_ value: Value) { self.value = value }
}
