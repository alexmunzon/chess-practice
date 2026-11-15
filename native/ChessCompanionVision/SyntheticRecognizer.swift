import Foundation
import CryptoKit

/// A deliberately limited native synthetic-pixel baseline. It accepts image
/// bytes and fixed bundled features, never FEN, filenames, scenes or truth.
public struct NativeSyntheticRecognizer {
    public static let implementationVersion = "swift-synthetic-pixels-v1"
    public static let expectedFeatureHash = "1dbebf15882b9ea926ac03b0a6ad7ac14092639ae142f53c4624df189d2e6fdb"
    private let labels = Array(".PNBRQKpnbrqk").map(String.init)
    private let features: [Double]
    private let backgrounds: [[Double]]
    private let energies: [[Double]]
    private let featureHash: String
    private let featureCount = 28 * 28 * 3
    private let markerNames = ["tl", "tr", "br", "bl"]
    private let markerCenters = [[32.0,32.0],[608.0,32.0],[608.0,608.0],[32.0,608.0]]
    private let markerColors = [[240.0,35.0,35.0],[35.0,220.0,75.0],[35.0,90.0,240.0],[235.0,35.0,220.0]]
    private let fixedPolicy: [String: Double] = ["maxTileRmse":0.055,"minTemplateMargin":0.012,"maxBorderRmse":0.045,"minEdgeRatio":0.40]

    struct Failure: Error, CustomStringConvertible { let description: String; init(_ text:String) {description=text} }

    public init(templateData: Data) throws {
        guard let value=try JSONSerialization.jsonObject(with:templateData) as? [String:Any],
              value["schemaVersion"] as? Int == 1,
              value["asset"] as? String == "owned-synthetic-classic-features-v1",
              value["labels"] as? String == ".PNBRQKpnbrqk",
              value["shape"] as? [Int] == [2,13,28,28,3],
              let encoded=value["featuresBase64"] as? String, let data=Data(base64Encoded:encoded),
              data.count == 2*13*28*28*3, let hash=value["featuresSha256"] as? String,
              hash==Self.expectedFeatureHash,Self.sha256(data)==hash,
              let colors=value["backgrounds"] as? [[Double]], colors.count==2, colors.allSatisfy({$0.count==3&&$0.allSatisfy({$0.isFinite})}),
              colors==[[231,216,184],[103,132,101]]
        else {throw Failure("invalid-fixed-template-assets")}
        let decoded=data.map{Double($0)/255.0}
        features=decoded;backgrounds=colors;featureHash=hash
        energies=(0..<2).map{side in (0..<13).map{label in
            let start=(side*13+label)*2352
            return PixelFeatures.edgeEnergy(Array(decoded[start..<start+2352]))
        }}
    }

    public static func sha256(_ data:Data)->String {SHA256.hash(data:data).map{String(format:"%02x",$0)}.joined()}

    private func markers(_ image:RGBImage)throws->[[String:Any]] {
        let scale=min(1.0,1280.0/Double(max(image.width,image.height)))
        let width=max(1,Int((Double(image.width)*scale).rounded(.toNearestOrEven))),height=max(1,Int((Double(image.height)*scale).rounded(.toNearestOrEven)))
        let pixels=scale==1 ? image.pixels : PixelFeatures.resizeRGB(image.pixels,width:image.width,height:image.height,toWidth:width,toHeight:height)
        guard pixels.count==width*height*3 else {throw Failure("marker-resize-failed")}
        var masks=[[Int]](repeating:[],count:4)
        for index in 0..<(width*height) {
            let red=Int(pixels[index*3]),green=Int(pixels[index*3+1]),blue=Int(pixels[index*3+2])
            if max(red,max(green,blue))-min(red,min(green,blue))<=70 {continue}
            let total=Float(max(red+green+blue,1))
            let chroma=[Double(Float(red)/total),Double(Float(green)/total),Double(Float(blue)/total)]
            for marker in 0..<4 {
                let color=markerColors[marker],sum=color.reduce(0,+)
                var distance=0.0
                for channel in 0..<3 {let delta=chroma[channel]-color[channel]/sum;distance+=delta*delta}
                if distance<0.12*0.12 {masks[marker].append(index)}
            }
        }
        var result=[[String:Any]]()
        for marker in 0..<4 {
            guard masks[marker].count>=16,Double(masks[marker].count)<=min(20_000.0,Double(width*height)*0.03) else {throw Failure("missing-or-excessive-marker-pixels")}
            var remaining=Set(masks[marker]),components=[[Int]]()
            while let start=remaining.first {
                remaining.remove(start);var found=[start],cursor=0
                while cursor<found.count {
                    let current=found[cursor],x=current%width,y=current/width;cursor+=1
                    for (nx,ny) in [(x-1,y),(x+1,y),(x,y-1),(x,y+1)] where nx>=0&&nx<width&&ny>=0&&ny<height {
                        let neighbor=ny*width+nx
                        if remaining.remove(neighbor) != nil {found.append(neighbor)}
                    }
                }
                components.append(found)
            }
            components.sort{$0.count>$1.count};let largest=components[0]
            guard largest.count>=16,components.count<2||Double(components[1].count)<Double(largest.count)*0.2 else {throw Failure("ambiguous-marker-components")}
            var minX=width,minY=height,maxX=0,maxY=0,sumX=0.0,sumY=0.0
            for pixel in largest {let x=pixel%width,y=pixel/width;minX=min(minX,x);maxX=max(maxX,x);minY=min(minY,y);maxY=max(maxY,y);sumX+=Double(x);sumY+=Double(y)}
            guard minX>0,minY>0,maxX<width-1,maxY<height-1 else {throw Failure("clipped-marker")}
            let boxWidth=Double(maxX-minX+1),boxHeight=Double(maxY-minY+1)
            guard boxWidth/boxHeight>=0.4,boxWidth/boxHeight<=2.5,Double(largest.count)/(boxWidth*boxHeight)>=0.45 else {throw Failure("unsupported-marker-shape")}
            let center=[(sumX/Double(largest.count)+0.5)*Double(image.width)/Double(width)-0.5,
                        (sumY/Double(largest.count)+0.5)*Double(image.height)/Double(height)-0.5]
            result.append(["name":markerNames[marker],"center":center,"detectedPixels":largest.count])
        }
        return result
    }

    private func solve(_ input:[[Double]],_ values:[Double])throws->[Double] {
        var matrix=zip(input,values).map{$0.0+[$0.1]}
        for column in 0..<8 {
            var pivot=column
            for row in column..<8 where abs(matrix[row][column])>abs(matrix[pivot][column]) {pivot=row}
            guard abs(matrix[pivot][column])>1e-12 else {throw Failure("singular-marker-projection")}
            matrix.swapAt(column,pivot);let divisor=matrix[column][column]
            for j in column...8 {matrix[column][j]/=divisor}
            for row in 0..<8 where row != column {let factor=matrix[row][column];for j in column...8 {matrix[row][j]-=factor*matrix[column][j]}}
        }
        return matrix.map{$0[8]}
    }

    private func rectify(_ image:RGBImage,_ detected:[[String:Any]])throws->(RGBImage,[[Double]]) {
        let points=detected.map{$0["center"] as! [Double]}
        var edges=[[Double]]()
        for index in 0..<4 {
            let next=points[(index+1)%4],current=points[index]
            edges.append([next[0]-current[0],next[1]-current[1]])
        }
        for i in 0..<4 {guard edges[i][0]*edges[(i+1)%4][1]-edges[i][1]*edges[(i+1)%4][0]>100 else {throw Failure("invalid-marker-order")}}
        var rows=[[Double]](),values=[Double]()
        for i in 0..<4 {
            let u=markerCenters[i][0]/640,v=markerCenters[i][1]/640,x=points[i][0],y=points[i][1]
            rows.append([u,v,1,0,0,0,-u*x,-v*x]);rows.append([0,0,0,u,v,1,-u*y,-v*y]);values += [x,y]
        }
        var matrix=try solve(rows,values)+[1.0],corners=[[Double]]()
        for (u,v) in [(0.0,0.0),(1.0,0.0),(1.0,1.0),(0.0,1.0)] {
            let denominator=matrix[6]*u+matrix[7]*v+1
            guard denominator.isFinite,abs(denominator)>=1e-9 else {throw Failure("invalid-panel-projection")}
            let x=(matrix[0]*u+matrix[1]*v+matrix[2])/denominator,y=(matrix[3]*u+matrix[4]*v+matrix[5])/denominator
            guard x.isFinite,y.isFinite,x>=(-1),y>=(-1),x<=Double(image.width+1),y<=Double(image.height+1) else {throw Failure("panel-outside-image")}
            corners.append([x,y])
        }
        for index in [0,1,3,4,6,7] {matrix[index]/=640}
        var output=[UInt8](repeating:0,count:640*640*3)
        for y in 0..<640 {for x in 0..<640 {
            let u=Double(x)+0.5,v=Double(y)+0.5,denominator=matrix[6]*u+matrix[7]*v+1
            let sourceX=(matrix[0]*u+matrix[1]*v+matrix[2])/denominator,sourceY=(matrix[3]*u+matrix[4]*v+matrix[5])/denominator
            if !sourceX.isFinite || !sourceY.isFinite || sourceX<0 || sourceY<0 || sourceX>=Double(image.width) || sourceY>=Double(image.height) {continue}
            let px=max(0,sourceX-0.5),py=max(0,sourceY-0.5),x0=Int(px),y0=Int(py),x1=min(x0+1,image.width-1),y1=min(y0+1,image.height-1),fx=px-Double(x0),fy=py-Double(y0)
            for c in 0..<3 {
                let top=Double(image.pixels[(y0*image.width+x0)*3+c])*(1-fx)+Double(image.pixels[(y0*image.width+x1)*3+c])*fx
                let bottom=Double(image.pixels[(y1*image.width+x0)*3+c])*(1-fx)+Double(image.pixels[(y1*image.width+x1)*3+c])*fx
                output[(y*640+x)*3+c]=UInt8(max(0,min(255,top*(1-fy)+bottom*fy)))
            }
        }}
        return (RGBImage(width:640,height:640,pixels:output),corners)
    }

    private func median(_ values:[Double])->Double {let sorted=values.sorted(),middle=sorted.count/2;return sorted.count%2==0 ? (sorted[middle-1]+sorted[middle])/2 : sorted[middle]}
    private func border(_ tile:[Double])->[Double] {
        var result=[Double]();result.reserveCapacity(2592)
        for row in 3..<61 {for column in 3..<61 where row<7||row>=57||column<7||column>=57 {let index=(row*64+column)*3;result.append(contentsOf:tile[index..<index+3])}}
        return result
    }
    private func backgroundMedian(_ tile:[Double])->[Double] {let values=border(tile);return (0..<3).map{channel in median(stride(from:channel,to:values.count,by:3).map{values[$0]})}}

    private func classify(_ panel:RGBImage)throws->([String:[String:Any]],[String:[Double]]) {
        var tiles=[[Double]]();tiles.reserveCapacity(64)
        for row in 0..<8 {for column in 0..<8 {var tile=[Double]();tile.reserveCapacity(64*64*3)
            for y in 0..<64 {let start=((64+row*64+y)*640+64+column*64)*3;tile.append(contentsOf:panel.pixels[start..<start+64*3].map(Double.init))};tiles.append(tile)
        }}
        let observedTiles=tiles.map(backgroundMedian)
        let observed=(0..<2).map{side in (0..<3).map{channel in median((0..<64).filter{($0/8+$0%8)%2==side}.map{observedTiles[$0][channel]})}}
        let gain=(0..<3).map{(observed[0][$0]-observed[1][$0])/(backgrounds[0][$0]-backgrounds[1][$0])}
        let offset=(0..<3).map{observed[0][$0]-gain[$0]*backgrounds[0][$0]}
        guard gain.allSatisfy({$0.isFinite&&$0>=0.4&&$0<=1.6}),offset.allSatisfy({$0.isFinite&&abs($0)<=80}) else {throw Failure("unsupported-board-palette-or-lighting")}
        var squares=[String:[String:Any]]()
        for index in 0..<64 {
            let dark=(index/8+index%8)%2,corrected=tiles[index].enumerated().map{($0.element-offset[$0.offset%3])/gain[$0.offset%3]}
            let feature=PixelFeatures.extract(corrected)
            guard feature.count==featureCount,feature.allSatisfy({$0.isFinite}) else {throw Failure("invalid-tile-features")}
            var residuals=[Double]()
            for label in 0..<13 {let base=(dark*13+label)*featureCount;var sum=0.0
                for j in 0..<featureCount {let delta=features[base+j]-feature[j];sum+=delta*delta};residuals.append(sqrt(sum/Double(featureCount)))
            }
            let order=(0..<13).sorted{residuals[$0]==residuals[$1] ? $0<$1 : residuals[$0]<residuals[$1]},best=order[0]
            let residual=residuals[best],margin=residuals[order[1]]-residual,edges=labels[best]=="." ? nil : PixelFeatures.edgeEnergy(feature)/max(energies[dark][best],1e-9)
            let borderValues=border(corrected);var sum=0.0
            for j in borderValues.indices {let delta=(borderValues[j]-backgrounds[dark][j%3])/255;sum+=delta*delta}
            let borderResidual=sqrt(sum/Double(borderValues.count));var reasons=[String]()
            if residual>0.055 {reasons.append("template-residual")};if margin<0.012 {reasons.append("ambiguous-template")}
            if borderResidual>0.045 {reasons.append("occluded-or-inconsistent-background")};if let energy=edges,energy<0.40 {reasons.append("insufficient-edge-detail")}
            squares[squareName(index)]=["rawLabel":labels[best],"label":reasons.isEmpty ? (labels[best]=="." ? "empty":labels[best]):"unknown",
                "confidence":reasons.isEmpty ? 1:0,"rawLabelAvailable":true,"templateRmse":residual,"runnerUpMargin":margin,"borderRmse":borderResidual,
                "edgeEnergyRatio":edges as Any? ?? NSNull(),"abstentionReasons":reasons]
        }
        return (squares,["gain":gain,"offset":offset])
    }

    private func squareName(_ index:Int)->String {String(Array("abcdefgh")[index%8])+String(8-index/8)}
    private func unknown(_ reason:String)->[String:[String:Any]] {Dictionary(uniqueKeysWithValues:(0..<64).map{(squareName($0),["rawLabel":".","label":"unknown","confidence":0,"rawLabelAvailable":false,"templateRmse":NSNull(),"runnerUpMargin":NSNull(),"borderRmse":NSNull(),"edgeEnergyRatio":NSNull(),"abstentionReasons":[reason]])})}
    private func placement(_ squares:[String:[String:Any]])->String {
        (0..<8).map{row in var output="",empty=0;for column in 0..<8 {let label=squares[squareName(row*8+column)]!["rawLabel"] as! String
            if label=="." {empty+=1}else{if empty>0 {output+=String(empty);empty=0};output+=label}};if empty>0 {output+=String(empty)};return output}.joined(separator:"/")
    }

    public func recognize(imageData:Data)throws->[String:Any] {
        let start=ProcessInfo.processInfo.systemUptime,image=try ImageDecoder.decode(imageData),decoded=ProcessInfo.processInfo.systemUptime
        var detected=[[String:Any]](),corners:[[Double]]?=nil,panel:RGBImage?=nil,reason:String?=nil
        do {detected=try markers(image);let result=try rectify(image,detected);panel=result.0;corners=result.1}catch{reason=String(describing:error)}
        let geometryDone=ProcessInfo.processInfo.systemUptime
        var squares=unknown("geometry-unavailable"),normalization:[String:[Double]]?=nil
        if let imagePanel=panel {do {let result=try classify(imagePanel);squares=result.0;normalization=result.1}catch{reason=String(describing:error);squares=unknown("unsupported-panel-appearance")}}
        let finished=ProcessInfo.processInfo.systemUptime,total=(finished-start)*1000
        return ["schemaVersion":1,"source":"synthetic-pixel-inference","model":"synthetic-screen-template-v1","pipelineVersion":"native-visible-markers-v1",
            "nativeImplementationVersion":Self.implementationVersion,"templateFeaturesSha256":featureHash,
            "sourceSha256":Self.sha256(imageData),"imageSize":[image.width,image.height],"status":"needs-human-review","fen":NSNull(),"guidanceAllowed":false,"threshold":0.95,
            "confidenceMeaning":"Binary fixed-template acceptance indicator (1 accepted, 0 abstained), not calibrated probability.",
            "rawPlacement":placement(squares),"rawPlacementAvailable":squares.values.allSatisfy{$0["rawLabelAvailable"] as? Bool==true},"squares":squares,
            "unknownSquares":squares.values.filter{$0["label"] as? String=="unknown"}.count,
            "geometry":["available":panel != nil,"markers":detected,"panelCorners":corners as Any? ?? NSNull(),"failureReason":reason as Any? ?? NSNull()],
            "photometricNormalization":normalization as Any? ?? NSNull(),"fixedPolicy":fixedPolicy,"elapsedMs":total,
            "timing":["decodeMs":(decoded-start)*1000,"geometryMs":(geometryDone-decoded)*1000,"classificationMs":(finished-geometryDone)*1000,"totalMs":total],
            "limitations":["Native Swift implementation; port conformance on reused synthetic data is separate from recognition accuracy.",
                "Synthetic marker-equipped rendered panels only; not physical pieces, glasses or camera evidence.",
                "Fixed classic templates only. Unknown appearance, occlusion or poor pixels may abstain and can still cause errors.",
                "No historical state, legal-move repair, temporal fill-in, FEN, seed or scene metadata enters recognition."]]
    }
}
