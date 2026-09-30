import CryptoKit
import Foundation

let line = readLine()!
let request = try JSONSerialization.jsonObject(with: Data(line.utf8)) as! [String: String]
let key = SymmetricKey(data: Data(base64Encoded: request["key"]!)!)
let blob = Data(base64Encoded: request["blob"]!)!
guard blob.starts(with: Data("AME1".utf8)) else { fatalError("invalid format") }
let box = try AES.GCM.SealedBox(combined: Data(blob.dropFirst(4)))
let clear = try AES.GCM.open(box, using: key, authenticating: Data(request["id"]!.utf8))
print(String(decoding: clear, as: UTF8.self))
