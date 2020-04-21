import inkex
from inkex import paths, bezier, transforms
from inkex.transforms import Transform
from bezmisc import *
from unicorn import entities
from unicorn import context
from lxml import etree
from math import radians
import sys, pprint

def parseLengthWithUnits( str ):
  '''
  Parse an SVG value which may or may not have units attached
  This version is greatly simplified in that it only allows: no units,
  units of px, and units of %.  Everything else, it returns None for.
  There is a more general routine to consider in scour.py if more
  generality is ever needed.
  '''
  u = 'px'
  s = str.strip()
  if s[-2:] == 'px':
    s = s[:-2]
  elif s[-2:] == 'in':
    u = 'in'
    s = s[:-2]
  elif s[-2:] == 'mm':
    u = 'mm'
    s = s[:-2]
  elif s[-1:] == '%':
    u = '%'
    s = s[:-1]
  try:
    v = float( s )
  except:
    return None, None
  return v, u

def subdivideCubicPath( sp, flat, i=1 ):
  """
  Break up a bezier curve into smaller curves, each of which
  is approximately a straight line within a given tolerance
  (the "smoothness" defined by [flat]).

  This is a modified version of cspsubdiv.cspsubdiv(). I rewrote the recursive
  call because it caused recursion-depth errors on complicated line segments.
  """

  while True:
    while True:
      if i >= len( sp ):
        return

      p0 = sp[i - 1][1]
      p1 = sp[i - 1][2]
      p2 = sp[i][0]
      p3 = sp[i][1]

      b = ( p0, p1, p2, p3 )

      if bezier.maxdist( b ) > flat:
        break

      i += 1

    one, two = bezier.beziersplitatt( b, 0.5 )
    sp[i - 1][2] = one[1]
    sp[i][0] = two[2]
    p = [one[2], one[3], two[1]]
    sp[i:1] = [p]

class SvgIgnoredEntity:
  def load(self,node,trans):
    self.tag = node.tag
  def __str__(self):
    return "Ignored '%s' tag" % self.tag
  def get_gcode(self,context):
    # context.codes.append("( tag " + str(self.tag) + ")")
    # context.codes.append("")
    return

class SvgPath(entities.PolyLine):
  def load(self, node, trans):
    a = node.get('style').split(";")
    d = dict(s.split(':') for s in a)
    if d['stroke'] == "#ff0000":
      self.cutStyle = 2
    elif d['stroke'] == "#0000ff":
      self.cutStyle = 3
    else:
      self.cutStyle = 1

    d = node.get('d')
    p = paths.Path(d)
    if len(p) == 0:
      return
    p = paths.CubicSuperPath(p)
    p = p.transform(trans)

    # p is now a list of lists of cubic beziers [ctrl p1, ctrl p2, endpoint]
    # where the start-point is the last point in the previous segment
    self.segments = []
    for sp in p:
      points = []
      subdivideCubicPath(sp,0.2)  # TODO: smoothness preference
      for csp in sp:
        points.append((csp[1][0],csp[1][1]))
      self.segments.append(points)

  def new_path_from_node(self, node):
    newpath = etree.Element(inkex.addNS('path','svg'))
    s = node.get('style')
    if s:
      newpath.set('style',s)
    t = node.get('transform')
    if t:
      newpath.set('transform',t)
    return newpath

class SvgRect(SvgPath):
  def load(self, node, trans):
    newpath = self.new_path_from_node(node)
    x = float(node.get('x'))
    y = float(node.get('y'))
    w = float(node.get('width'))
    h = float(node.get('height'))
    a = []
    a.append(['M', [x,y]])
    a.append(['l', [w,0]])
    a.append(['l', [0,h]])
    a.append(['l', [-w,0]])
    a.append(['Z', []])

    newpath.set('d', str(paths.Path(a)))
    SvgPath.load(self,newpath,trans)

class SvgLine(SvgPath):
  def load(self, node, trans):
    newpath = self.new_path_from_node(node)
    x1 = float(node.get('x1'))
    y1 = float(node.get('y1'))
    x2 = float(node.get('x2'))
    y2 = float(node.get('y2'))
    a = []
    a.append(['M', [x1,y1]])
    a.append(['L', [x2,y2]])
    newpath.set('d', str(path.Path(a)))
    SvgPath.load(self,newpath,trans)

class SvgPolyLine(SvgPath):
  def load(self, node, trans):
    newpath = self.new_path_from_node(node)
    pl = node.get('points','').strip()
    if pl == '':
      return
    pa = pl.split()
    if not len(pa):
      return

    d = "M " + pa[0]
    for i in range(1, len(pa)):
      d += " L " + pa[i]
    newpath.set('d',d)
    SvgPath.load(self,newpath,trans)

class SvgEllipse(SvgPath):
  def load(self, node,trans):
    rx = float(node.get('rx','0'))
    ry = float(node.get('ry','0'))
    SvgPath.load(self,self.make_ellipse_path(rx,ry,node), trans)
  def make_ellipse_path(self, rx, ry, node):
    if rx == 0 or ry == 0:
      return None
    cx = float(node.get('cx','0'))
    cy = float(node.get('cy','0'))
    x1 = cx - rx
    x2 = cx + rx
    d = 'M %f,%f ' % (x1,cy) + \
      'A %f,%f ' % (rx,ry) + \
      '0 1 0 %f, %f ' % (x2,cy) + \
      'A %f,%f ' % (rx,ry) + \
      '0 1 0 %f,%f' % (x1,cy)
    newpath = self.new_path_from_node(node)
    newpath.set('d',d)
    return newpath

class SvgCircle(SvgEllipse):
  def load(self, node,trans):
    rx = float(node.get('r','0'))
    SvgPath.load(self,self.make_ellipse_path(rx,rx,node), trans)

class SvgText(SvgIgnoredEntity):
  def load(self,node,trans):
    inkex.errormsg('Warning: unable to draw text. please convert it to a path first.')
    SvgIgnoredEntity.load(self,node,trans)

class SvgLayerChange():
  def __init__(self,layer_name):
    self.layer_name = layer_name
  def get_gcode(self,context):
    context.codes.append("M01 (Plotting layer '%s')" % self.layer_name)

class SvgParser:

  entity_map = {
    'path': SvgPath,
    'rect': SvgRect,
    'line': SvgLine,
    'polyline': SvgPolyLine,
    'polygon': SvgPolyLine,
    'circle': SvgCircle,
    'ellipse': SvgEllipse,
    'pattern': SvgIgnoredEntity,
    'metadata': SvgIgnoredEntity,
    'defs': SvgIgnoredEntity,
    'eggbot': SvgIgnoredEntity,
    ('namedview','sodipodi'): SvgIgnoredEntity,
    'text': SvgText
  }

  def __init__(self, svg):
    self.svg = svg
    self.entities = []

  def getLength( self, name ):
    '''
    Get the <svg> attribute with name "name" and default value "default"
    Parse the attribute into a value and associated units.  Then, accept
    no units (''), units of pixels ('px'), and units of percentage ('%').
    '''
    str = self.svg.get( name )
    if str:
      v, u = parseLengthWithUnits( str )
      if not v:
        # Couldn't parse the value
        return None
      elif ( u == '' ) or ( u == 'px' ):
        return v * 0.26458
      elif ( u == 'in' ):
        return v * 25.4
      elif ( u == 'mm' ):
        return v
      elif u == '%':
        return None
      else:
        # Unsupported units
        return None
    else:
      # No width specified; assume the default value
      return None

  def parse(self):
    # 0.28222 scale determined by comparing pixels-per-mm in a default Inkscape file.
    # self.svgWidth = self.getLength('width', 354) * 0.28222
    # self.svgHeight = self.getLength('height', 354) * 0.28222
    self.svgHeight = self.getLength('height') 
    self.recursivelyTraverseSvg(self.svg, Transform([[1.0, 0.0, 0], [0.0, -1.0, self.svgHeight]]))
    # self.recursivelyTraverseSvg(self.svg)

  # TODO: center this thing
  def recursivelyTraverseSvg(self, nodeList, 
                             transCurrent = Transform([[1.0, 0.0, 0.0], [0.0, -1.0, 0.0]]),
                             parent_visibility = 'visible'):
    """
    Recursively traverse the svg file to plot out all of the
    paths.  The function keeps track of the composite transformation
    that should be applied to each path.

    This function handles path, group, line, rect, polyline, polygon,
    circle, ellipse and use (clone) elements. Notable elements not
    handled include text.  Unhandled elements should be converted to
    paths in Inkscape.

    TODO: There's a lot of inlined code in the eggbot version of this
    that would benefit from the Entities method of dealing with things.
    """
    for node in nodeList:
      # Ignore invisible nodes
      v = node.get('visibility', parent_visibility)
      if v == 'inherit':
        v = parent_visibility
      if v == 'hidden' or v == 'collapse':
        pass

      # first apply the current matrix transform to this node's transform

      trans = Transform(node.get("transform"));
      transNew = transCurrent * trans

      if node.tag == inkex.addNS('g','svg') or node.tag == 'g':
        if (node.get(inkex.addNS('groupmode','inkscape')) == 'layer'):
          layer_name = node.get(inkex.addNS('label','inkscape'))

        self.recursivelyTraverseSvg(node, transNew, parent_visibility = v)
      elif node.tag == inkex.addNS('use','svg') or node.tag == 'use':
        refid = node.get(inkex.addNS('href','xlink'))
        if refid:
          # [1:] to ignore leading '#' in reference
          path = '//*[@id="%s"]' % refid[1:]
          refnode = node.xpath( path )
          if refnode:
            x = float(node.get('x','0'))
            y = float(node.get('y','0'))
            # Note: the transform has already been applied
            if (x!=0) or (y!=0):
              transNew2 = transNew * parseTransform('translate(%f,%f)' % (x,y))
            else:
              transNew2 = transNew
            v = node.get('visibility',v)
            self.recursivelyTraverseSvg(refnode,transNew2,parent_visibility=v)
          else:
            pass
        else:
          pass
      elif not isinstance(node.tag, str):
        pass
      else:
        entity = self.make_entity(node, transNew)
        if entity == None:
          inkex.errormsg('Warning: unable to draw object, please convert it to a path first.')

  def make_entity(self,node,trans):
    for nodetype in SvgParser.entity_map.keys():
      tag = nodetype
      ns = 'svg'
      if(type(tag) is tuple):
        tag = nodetype[0]
        ns = nodetype[1]
      if node.tag == inkex.addNS(tag,ns) or node.tag == tag:
        constructor = SvgParser.entity_map[nodetype]
        entity = constructor()
        entity.load(node,trans)
        self.entities.append(entity)
        return entity
    return None
