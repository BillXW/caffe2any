"""
http://www.bogotobogo.com/python/python_graph_data_structures.php
A set of classes to model a DL topology

Todo: add find_input_blobs
Todo: remove Node.layer
"""
from collections import OrderedDict, Counter
DEBUG = False
import copy

def debug(str):
    if DEBUG: 
        print (str)

class Node:
    def __init__(self, name, type, layer):
        self.name = name
        self.type = type
        self.layer = layer
    def __str__(self):
        return self.name + '(' + self.type + ')'

class PoolingNode(Node):
    def __init__(self, name, type, layer):
        Node.__init__(self, name, type, layer)
        param = layer.pooling_param
        self.kernel_size = param.kernel_size
        self.stride = param.stride
        self.pad = param.pad

    def transform(self, ifm_shape):
        ofm_shape = copy.deepcopy(ifm_shape)

        ifmh = ifm_shape[2]
        ofmh = (ifmh - self.kernel_size + 2*self.pad) / self.stride + 1
        ofm_shape[2] = ofmh
        ofm_shape[3] = ofmh
        #print (str(ifm_shape) + '--> ' + str(ofm_shape))
        return ofm_shape

class ConvolutionNode(Node):
    def __init__(self, name, type, layer):
        Node.__init__(self, name, type, layer)
        param = layer.convolution_param
        self.kernel_size = param.kernel_size
        self.stride = param.stride
        self.pad = param.pad
        self.num_output = param.num_output

    def transform(self, ifm_shape):
        ofm_shape = copy.deepcopy(ifm_shape)
        ofm_shape[1] = self.num_output
        ifmh = ifm_shape[2]
        ofmh = (ifmh - self.kernel_size + 2*self.pad) / self.stride + 1
        ofm_shape[2] = ofmh
        ofm_shape[3] = ofmh
        #print (str(ifm_shape) + '--> ' + str(ofm_shape))
        return ofm_shape

def node_factory(name, type, layer):
    if type == "Pooling":
        new_node = PoolingNode(name, type, layer)
    elif type == "Convolution":
        new_node = ConvolutionNode(name, type, layer)
    else:    
        new_node = Node(name, type, layer)
    return new_node

class BLOB:
    def __init__(self, name, shape, producer):
        self.name = name
        self.shape = shape
        self.producer = producer
        #print (self.shape)

    def __str__(self):
        if self.shape != None:
            return 'BLOB [' + self.name + ': shape=' + str(self.shape) + ']'
        else:
            return 'BLOB [' + self.name + ']'

class Edge:
    def __init__(self, src_node, dst_node, blob):
        self.src_node = src_node
        self.dst_node = dst_node
        self.blob = blob

    def __str__(self):
        return ('Edge [' + str(self.blob) +  ': ' + (self.src_node.name if self.src_node else 'None') + ' ==> ' + 
                (self.dst_node.name if self.dst_node else 'None') +  ']')

class Topology:
    def __init__(self):
        """
        Keep the the vertices ordered by insertion, so that we have 
        a starting point
        """
        self.nodes = OrderedDict()
        self.blobs = {}
        self.edges = []

    def add_node(self, name, type, layer):
        new_node = node_factory(name, type, layer)
        self.nodes[name] = new_node
        debug('created Node:' + name)
        return new_node

    def add_blob(self, name, shape, producer):
        new_blob = BLOB(name, shape, producer)
        self.blobs[name] = new_blob
        debug('created:' + str(new_blob))
        return new_blob

    def add_edge(self, src, dst, blob):
        new_edge = Edge(src, dst, blob)
        self.edges.append(new_edge)
        debug('created:' + str(new_edge))
        return new_edge

    def get_start_node(self):
        return self.nodes.values()[0]

    def find_blob(self, name):
        if name not in self.blobs:
            return None
        return self.blobs[name]

    def find_outgoing_edges(self, node):
        edges = []
        for edge in self.edges:
            if (edge.src_node != None) and (edge.src_node.name == node.name):
                edges.append(edge)
        return edges

    def find_incoming_edges(self, node):
        edges = []
        for edge in self.edges:
            if (edge.dst_node != None) and (edge.dst_node.name == node.name):
                edges.append(edge)
        return edges

    # Output BLOBs have no consumer and therefore they don't appear on an edge.
    # We scan all blobs, checking which blobs don't appear on an edge
    # TODO: THIS HAS A BUG (Works only the first time!!!!)
    def find_output_blobs(self):
        blobs = []
        for blob in self.blobs:
            blob_has_consumer = False
            for edge in self.edges:
                if edge.blob.name == blob:
                    blob_has_consumer = True
                    continue
            if blob_has_consumer == False:
                blobs.append(blob)
        return blobs

    def traverse(self, node_cb, edge_cb=None):
        """
        BFS traversal of the topology graph
        """
        pending = [ self.get_start_node() ]
        while len(pending)>0:
            node = pending.pop()
            if node_cb != None: node_cb(node)
            outgoing_edges = self.find_outgoing_edges(node)
            for edge in outgoing_edges:
                if edge_cb!=None: edge_cb(edge)
                if edge.dst_node!=None: pending.append(edge.dst_node)

def populate(caffe_net):
    """
    Create and populate a Topology object, based on a given Caffe protobuf network object
    Todo: fix Input assignment
    """
    graph = Topology()

    # Input BLOBs
    for i in range(len(caffe_net.input)):
        graph.add_blob(caffe_net.input[i], caffe_net.input_shape[i].dim, None)

    for layer in caffe_net.layer:
        debug('evaluating layer: ' + layer.name)

        # filter away layers used only in training phase
        phase = 1 #caffe_pb2.Phase.TEST
        if phase is not None:
          included = False
          if len(layer.include) == 0:
            included = True
          if len(layer.include) > 0 and len(layer.exclude) > 0:
            raise ValueError('layer ' + layer.name + ' has both include '
                             'and exclude specified.')
          for layer_phase in layer.include:
            included = included or layer_phase.phase == phase
          for layer_phase in layer.exclude:
            included = included and not layer_phase.phase == phase
          if not included:
            continue
        
        # Some prototxt files don't set the 'layer.exclude/layer.include' attributes.
        # Therefore, manually filter training-only layers
        if layer.type in ['Dropout']:
            continue

        new_node = graph.add_node(layer.name, layer.type, layer)

        # Iterate over BLOBs consumed by this layer and create edges to them
        for bottom_blob in layer.bottom:
            blob = graph.find_blob(bottom_blob)
            if blob == None:
                raise ValueError('could not find BLOB:' + bottom_blob)

            edge = graph.add_edge(src=blob.producer, dst=new_node, blob=blob)  

        # Add the BLOBs produced by this layer to the topology
        for top_blob in layer.top:
            graph.add_blob(top_blob, None, producer = new_node)

    # Add fake output edges
    output_blobs = graph.find_output_blobs()
    for blob_name in output_blobs:
        blob = graph.find_blob(blob_name)
        graph.add_edge(src=blob.producer, dst=None, blob=blob)  

    return graph