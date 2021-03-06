#!/usr/bin/python

"""

"""
import sys
import argparse
from collections import deque, Counter
import caffe_pb2 as caffe
#import parsers.protos.caffe_pb2 as caffe
import parsers.protos.caffe2_pb2 as caffe2
from google.protobuf import text_format
from printers import csv, console, png
from parsers.caffe_parser import parse_caffe_net
from parsers.caffe2_parser import parse_caffe2_net
from transforms import reduce_transforms
import topology
import yaml
import logging
import ntpath
import os
import logging.config

''' This is a crude dynamic load of printer classes.
In the future, need to make this nicer.
This provides the ability to dynamically load printers from other
code bases.
'''
import inspect
import importlib

def load_printer(printer_type, my_class=None):
    if my_class == None:
        module = importlib.import_module('printers')
        return getattr(module, printer_type)

    mod_name = 'printers.{0}'.format(printer_type)
    try:
        module = importlib.import_module(mod_name)
        return getattr(module, my_class)
    except ImportError:
        return None


def sum_blob_mem(tplgy, node, blobs, sum):
    if node.type == "Input" or node.role == "Modifier":
        return
    out_edges = tplgy.find_outgoing_edges(node)
    for out_edge in out_edges:
        if out_edge.blob not in blobs:
            shape = out_edge.blob.shape
            sum[0] += out_edge.blob.size()
            blobs.append(out_edge.blob)

from transforms.update_blobs_sizes import update_blobs_sizes
from transforms import fold_transforms
from transforms import decorator_transforms


def test_bfs(tplgy):
    #tplgy.traverse(lambda node: print(node))
    tplgy.traverse(None, lambda edge: print(edge))


def apply_transforms(prefs, tplgy):
    ''' Handle optional transform processing on the topology
    '''
    if prefs['remove_dropout']:
        tplgy.remove_op_by_type('Dropout')
    if prefs['merge_conv_relu']:
        tplgy.merge_ops('Convolution', 'ReLU')
    if prefs['merge_ip_relu']:
        tplgy.merge_ops('InnerProduct', 'ReLU')
    if prefs['merge_sum_relu']:
        tplgy.merge_ops('Eltwise', 'ReLU')
    if prefs['merge_conv_relu_pooling']:
        tplgy.merge_ops('Convolution_ReLU', 'Pooling')
    if prefs['fold_scale']:
        fold_transforms.fold_pair(tplgy, 'Convolution', 'Scale')
        fold_transforms.fold_pair(tplgy, 'Convolution_ReLU', 'Scale')
    if prefs['fold_batchnorm']:
        fold_transforms.fold_pair(tplgy, 'Convolution', 'BatchNorm')
        fold_transforms.fold_pair(tplgy, 'Convolution_ReLU', 'BatchNorm')
    #decorator_transforms.horizontal_fusion(tplgy)

def get_outfile(infile):
    outdir = 'output/'
    if not os.path.exists(outdir):
        os.makedirs(outdir)
    outfile = outdir + ntpath.basename(infile)
    return outfile

def main():
    print("caffe2any v0.5")
    parser = argparse.ArgumentParser()
    parser.add_argument('-p', '--printer', help='output printer (csv, console, png)', default='console')
    parser.add_argument('-d', '--display', type=str, help='display inventory,unique,output,bfs,mem')
    parser.add_argument('-w', '--workdir', type=str, help='set the working directory', default='.')
    parser.add_argument('infile', help='input prototxt file')
    args = parser.parse_args()

    os.chdir(args.workdir)
    logging.config.fileConfig('config/logging.conf')
    logger = logging.getLogger('topology')

    EXPERIMENTAL = False
    if EXPERIMENTAL:
        # python caffe2any.py examples/caffe2/alexnet_predict_net.pb -p png -d inventory
        f = open(sys.argv[1], "rb")
        net = caffe2.NetDef()
        net.ParseFromString(f.read())
        tplgy = parse_caffe2_net(net)
        exit()
    else:
        net = caffe.NetParameter()

        # Read a Caffe prototxt file
        try:
            f = open(sys.argv[1], "rb")
            text_format.Parse(f.read(), net)
            f.close()
        except IOError:
            exit("Could not open file " + sys.argv[1])

        tplgy = parse_caffe_net(net)

    # read preferences
    with open("config/caffe2any_cfg.yml", 'r') as cfg_file:
        prefs = yaml.load(cfg_file)

    apply_transforms(prefs['transforms'], tplgy)

    #test_bfs(tplgy)
    # calculate BLOBs sizes
    update_blobs_sizes(tplgy)
    #decorator_transforms.add_size_annotations(tplgy)
    # Remove Concat layers only after updating the BLOB sizes
    fold_transforms.concat_removal(tplgy)

    outfile = get_outfile(args.infile)
    for printer_str in args.printer.split(','):
        if printer_str == 'console':
            printer = console.ConsolePrinter()
        elif printer_str == 'png':
            printer = png.PngPrinter(outfile, prefs['png'], net)
        elif printer_str == 'csv':
            printer = csv.CsvPrinter(outfile)
        else:
            # dynamically load a printer module
            printer_ctor = load_printer(printer_str, 'Printer')
            if printer_ctor is not None:
                printer = printer_ctor(args)
            else:
                print("Printer {} is not supported".format(printer_str))
                exit()

        if args.display != None:
            for disp_opt in args.display.split(','):
                if disp_opt == 'inventory':
                    printer.print_inventory( reduce_transforms.get_inventory(tplgy) )
                elif disp_opt == 'unique':
                    printer.print_unique_all( reduce_transforms.get_uniques_inventory(tplgy) )
                elif disp_opt == 'output':
                    print("outputs:")
                    outputs = tplgy.find_output_blobs()
                    for output in outputs:
                        print('\t' + output)
                elif disp_opt == 'bfs':
                    printer.print_bfs(tplgy)
                elif disp_opt == 'mem':
                    sum = [0]
                    blobs = []
                    tplgy.traverse(lambda node: sum_blob_mem(tplgy, node, blobs, sum))
                    print("Total BLOB memory: " + str(sum[0]))
                else:
                    exit ("Error: invalid display option")


if __name__ == '__main__':
    main()
