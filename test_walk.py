import OCP.STEPCAFControl
import OCP.TCollection
import OCP.TDocStd
import OCP.XCAFDoc
import OCP.TDF
import OCP.TDataStd

doc = OCP.TDocStd.TDocStd_Document(OCP.TCollection.TCollection_ExtendedString('slac-step-doc'))
reader = OCP.STEPCAFControl.STEPCAFControl_Reader()
status = reader.ReadFile('step_files/DSG-000046520.stp')
transferred = reader.Transfer(doc)

shape_tool = OCP.XCAFDoc.XCAFDoc_DocumentTool.ShapeTool_s(doc.Main())

labels = OCP.TDF.TDF_LabelSequence()
shape_tool.GetFreeShapes(labels)
l = labels.Value(1)

# FindAttribute takes the attribute ID and an attribute object reference
name_attr = OCP.TDataStd.TDataStd_Name()
if l.FindAttribute(OCP.TDataStd.TDataStd_Name.GetID_s(), name_attr):
    ext_str = name_attr.Get()
    print("Type of ext_str:", type(ext_str))
    print("Methods:", dir(ext_str))
    # Let's try str(ext_str) or printing directly
    print("str:", str(ext_str))
else:
    print("Name attribute not found")

