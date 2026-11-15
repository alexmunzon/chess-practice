import Foundation
import CryptoKit

/// A deliberately limited native synthetic-pixel baseline. It accepts image
/// bytes and fixed bundled features, never FEN, filenames, scenes or truth.
public struct NativeSyntheticRecognizer: Sendable {
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
        // Each marker's target chromaticity color[channel]/sum, hoisted out of the pixel loop
        // (the same Double values the per-pixel expression produced).
        let targets=markerColors.flatMap{color in let sum=color.reduce(0,+);return color.map{$0/sum}}
        var masks=[[Int]](repeating:[],count:4)
        pixels.withUnsafeBufferPointer{source in targets.withUnsafeBufferPointer{target in
            for index in 0..<(width*height) {
                let red=Int(source[index*3]),green=Int(source[index*3+1]),blue=Int(source[index*3+2])
                if max(red,max(green,blue))-min(red,min(green,blue))<=70 {continue}
                let total=Float(max(red+green+blue,1))
                let chroma0=Double(Float(red)/total),chroma1=Double(Float(green)/total),chroma2=Double(Float(blue)/total)
                for marker in 0..<4 {
                    var distance=0.0
                    let delta0=chroma0-target[marker*3];distance+=delta0*delta0
                    let delta1=chroma1-target[marker*3+1];distance+=delta1*delta1
                    let delta2=chroma2-target[marker*3+2];distance+=delta2*delta2
                    if distance<0.12*0.12 {masks[marker].append(index)}
                }
            }
        }}
        var result=[[String:Any]]()
        // One membership buffer reused per marker: every set entry is cleared again by the flood fill.
        var pending=[Bool](repeating:false,count:width*height)
        for marker in 0..<4 {
            guard masks[marker].count>=16,Double(masks[marker].count)<=min(20_000.0,Double(width*height)*0.03) else {throw Failure("missing-or-excessive-marker-pixels")}
            // 4-connected components of the mask. The component sets are the same as the earlier
            // Set-based search; only discovery order differs, which no decision depends on
            // (integer coordinate sums are exact in Double, ties at the top already fail closed).
            var components=[[Int]]()
            pending.withUnsafeMutableBufferPointer{member in
                for pixel in masks[marker] {member[pixel]=true}
                for start in masks[marker] where member[start] {
                    member[start]=false;var found=[start],cursor=0
                    while cursor<found.count {
                        let current=found[cursor],x=current%width,y=current/width;cursor+=1
                        if x>0 && member[current-1] {member[current-1]=false;found.append(current-1)}
                        if x+1<width && member[current+1] {member[current+1]=false;found.append(current+1)}
                        if y>0 && member[current-width] {member[current-width]=false;found.append(current-width)}
                        if y+1<height && member[current+width] {member[current+width]=false;found.append(current+width)}
                    }
                    components.append(found)
                }
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
        let m0=matrix[0],m1=matrix[1],m2=matrix[2],m3=matrix[3],m4=matrix[4],m5=matrix[5],m6=matrix[6],m7=matrix[7]
        let imageWidth=image.width,imageHeight=image.height,sourceWidth=Double(image.width),sourceHeight=Double(image.height)
        image.pixels.withUnsafeBufferPointer{pixels in output.withUnsafeMutableBufferPointer{target in
            for y in 0..<640 {for x in 0..<640 {
                let u=Double(x)+0.5,v=Double(y)+0.5,denominator=m6*u+m7*v+1
                let sourceX=(m0*u+m1*v+m2)/denominator,sourceY=(m3*u+m4*v+m5)/denominator
                if !sourceX.isFinite || !sourceY.isFinite || sourceX<0 || sourceY<0 || sourceX>=sourceWidth || sourceY>=sourceHeight {continue}
                let px=max(0,sourceX-0.5),py=max(0,sourceY-0.5),x0=Int(px),y0=Int(py),x1=min(x0+1,imageWidth-1),y1=min(y0+1,imageHeight-1),fx=px-Double(x0),fy=py-Double(y0)
                let i00=(y0*imageWidth+x0)*3,i01=(y0*imageWidth+x1)*3,i10=(y1*imageWidth+x0)*3,i11=(y1*imageWidth+x1)*3,o=(y*640+x)*3
                for c in 0..<3 {
                    let top=Double(pixels[i00+c])*(1-fx)+Double(pixels[i01+c])*fx
                    let bottom=Double(pixels[i10+c])*(1-fx)+Double(pixels[i11+c])*fx
                    target[o+c]=UInt8(max(0,min(255,top*(1-fy)+bottom*fy)))
                }
            }}
        }}
        return (RGBImage(width:640,height:640,pixels:output),corners)
    }

    private func median(_ values:[Double])->Double {let sorted=values.sorted(),middle=sorted.count/2;return sorted.count%2==0 ? (sorted[middle-1]+sorted[middle])/2 : sorted[middle]}
    private func border(_ tile:[Double])->[Double] {
        var result=[Double]();result.reserveCapacity(2592)
        tile.withUnsafeBufferPointer{values in
            for row in 3..<61 {for column in 3..<61 where row<7||row>=57||column<7||column>=57 {let index=(row*64+column)*3;result.append(values[index]);result.append(values[index+1]);result.append(values[index+2])}}
        }
        return result
    }
    private func backgroundMedian(_ tile:[Double])->[Double] {let values=border(tile);return (0..<3).map{channel in median(stride(from:channel,to:values.count,by:3).map{values[$0]})}}

    private func classify(_ panel:RGBImage)throws->([String:[String:Any]],[String:[Double]]) {
        var tiles=[[Double]]();tiles.reserveCapacity(64)
        panel.pixels.withUnsafeBufferPointer{pixels in
            for row in 0..<8 {for column in 0..<8 {var tile=[Double](repeating:0,count:64*64*3)
                tile.withUnsafeMutableBufferPointer{output in
                    for y in 0..<64 {let start=((64+row*64+y)*640+64+column*64)*3;for k in 0..<64*3 {output[y*64*3+k]=Double(pixels[start+k])}}
                };tiles.append(tile)
            }}
        }
        let observedTiles=tiles.map(backgroundMedian)
        let observed=(0..<2).map{side in (0..<3).map{channel in median((0..<64).filter{($0/8+$0%8)%2==side}.map{observedTiles[$0][channel]})}}
        let gain=(0..<3).map{(observed[0][$0]-observed[1][$0])/(backgrounds[0][$0]-backgrounds[1][$0])}
        let offset=(0..<3).map{observed[0][$0]-gain[$0]*backgrounds[0][$0]}
        guard gain.allSatisfy({$0.isFinite&&$0>=0.4&&$0<=1.6}),offset.allSatisfy({$0.isFinite&&abs($0)<=80}) else {throw Failure("unsupported-board-palette-or-lighting")}
        var squares=[String:[String:Any]]()
        let featureCount=self.featureCount
        var corrected=[Double](repeating:0,count:64*64*3)
        for index in 0..<64 {
            let dark=(index/8+index%8)%2
            let offset0=offset[0],offset1=offset[1],offset2=offset[2],gain0=gain[0],gain1=gain[1],gain2=gain[2]
            tiles[index].withUnsafeBufferPointer{tile in corrected.withUnsafeMutableBufferPointer{output in
                for j in stride(from:0,to:tile.count,by:3) {
                    output[j]=(tile[j]-offset0)/gain0;output[j+1]=(tile[j+1]-offset1)/gain1;output[j+2]=(tile[j+2]-offset2)/gain2
                }
            }}
            let feature=PixelFeatures.extract(corrected)
            guard feature.count==featureCount,feature.allSatisfy({$0.isFinite}) else {throw Failure("invalid-tile-features")}
            // 13 independent running sums advanced together. Each label's sum still adds its
            // terms in the same j order as before, so every residual is bit-identical; only the
            // interleaving across labels changes (no floating-point reassociation).
            var residuals=[Double](repeating:0,count:13)
            features.withUnsafeBufferPointer{templates in feature.withUnsafeBufferPointer{observed in residuals.withUnsafeMutableBufferPointer{sums in
                let base=dark*13*featureCount
                for j in 0..<featureCount {
                    let value=observed[j]
                    for label in 0..<13 {let delta=templates[base+label*featureCount+j]-value;sums[label]+=delta*delta}
                }
                for label in 0..<13 {sums[label]=sqrt(sums[label]/Double(featureCount))}
            }}}
            let order=(0..<13).sorted{residuals[$0]==residuals[$1] ? $0<$1 : residuals[$0]<residuals[$1]},best=order[0]
            let residual=residuals[best],margin=residuals[order[1]]-residual,edges=labels[best]=="." ? nil : PixelFeatures.edgeEnergy(feature)/max(energies[dark][best],1e-9)
            let borderValues=border(corrected);var sum=0.0
            let background=backgrounds[dark]
            borderValues.withUnsafeBufferPointer{values in
                for j in 0..<values.count {let delta=(values[j]-background[j%3])/255;sum+=delta*delta}
            }
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
