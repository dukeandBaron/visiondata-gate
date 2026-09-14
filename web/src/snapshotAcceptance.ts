export type AnnotationRequirement = "REQUIRED" | "OPTIONAL" | "NOT_APPLICABLE" | "UNKNOWN";
export interface AcceptanceRow {
  asset: {asset_id: string; source_sha256: string};
  state: {asset_id: string; revision: number; document_sha256: string; annotations: Array<{label: string}>};
  split: "train" | "val" | "test";
  category: string;
  requirement: AnnotationRequirement;
}
export interface OperatorAcceptanceRequirements {
  schema_version: "visiondata-gate.operator-acceptance-requirements.v1";
  purpose_description: string;
  category_vocabulary: string[];
  samples: Array<{
    asset_id: string; split: "train" | "val" | "test"; category: string;
    annotation_requirement: AnnotationRequirement;
    human_review: {reviewer_name: string; note: string; expected_asset_sha256: string; expected_annotation_revision: number; expected_annotation_sha256: string; operator_attests_reviewed: true};
  }>;
}
function compareCodepoints(a: string, b: string): number {
  const left=Array.from(a), right=Array.from(b);
  for(let i=0;i<Math.min(left.length,right.length);i++) {
    const difference=left[i]!.codePointAt(0)!-right[i]!.codePointAt(0)!;
    if(difference) return difference;
  }
  return left.length-right.length;
}
export function makeAcceptanceRequirements(input: {purpose: string; vocabulary: string; reviewer: string; note: string; attested: boolean; rows: AcceptanceRow[]}): OperatorAcceptanceRequirements {
  if(!input.attested || input.reviewer.trim().length<2 || input.note.trim().length<8) throw new Error("请填写复核姓名、规范说明，并确认已逐项复核。");
  if(input.purpose.trim().length<8 || input.purpose.trim().length>1000) throw new Error("用途说明需要 8–1000 个字符。");
  const vocabulary=[...new Set(input.vocabulary.split(/[,，\n]/).map(value=>value.trim()).filter(Boolean))].sort(compareCodepoints);
  if(!vocabulary.length || vocabulary.some(value=>value.length>120)) throw new Error("请填写有效类别词表。");
  if(!input.rows.length || new Set(input.rows.map(row=>row.asset.asset_id)).size!==input.rows.length) throw new Error("资产范围为空或重复，请重新读取。");
  const samples=input.rows.map(row=>{
    if(row.asset.asset_id!==row.state.asset_id || !/^[0-9a-f]{64}$/.test(row.state.document_sha256)) throw new Error("标注版本绑定不一致，请重新读取。");
    if(row.requirement==='UNKNOWN') throw new Error("存在未明确的标注要求，不能冻结。");
    if(row.requirement==='REQUIRED'&&!row.state.annotations.length) throw new Error("存在缺少必需标注的图片，请先补充标注。");
    if(row.requirement==='NOT_APPLICABLE'&&row.state.annotations.length) throw new Error("已有标注的图片不能声明标注不适用。");
    const category=row.category.trim();
    if(!vocabulary.includes(category)||row.state.annotations.some(box=>!vocabulary.includes(box.label))) throw new Error("样本类别或已有框标签不在词表内。");
    return {asset_id:row.asset.asset_id,split:row.split,category,annotation_requirement:row.requirement,human_review:{reviewer_name:input.reviewer.trim(),note:input.note.trim(),expected_asset_sha256:row.asset.source_sha256,expected_annotation_revision:row.state.revision,expected_annotation_sha256:row.state.document_sha256,operator_attests_reviewed:true as const}};
  }).sort((a,b)=>compareCodepoints(a.asset_id,b.asset_id));
  return {schema_version:'visiondata-gate.operator-acceptance-requirements.v1',purpose_description:input.purpose.trim(),category_vocabulary:vocabulary,samples};
}
