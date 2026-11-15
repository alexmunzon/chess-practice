import Foundation

#if SWIFT_PACKAGE
extension NativeSyntheticRecognizer {
    /// Library-only iPhone initialization; all assets are bundled locally.
    public static func bundled() throws -> NativeSyntheticRecognizer {
        guard let url=Bundle.module.url(forResource:"classic-templates-v1",withExtension:"json") else {
            throw Failure("missing-bundled-template-assets")
        }
        return try NativeSyntheticRecognizer(templateData:Data(contentsOf:url))
    }
}
#endif
